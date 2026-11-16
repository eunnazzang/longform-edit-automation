"""유튜브 공식 API 업로더 (YouTube Data API v3, videos.insert).

예약시각이 미래인 행은 publishAt(서버 예약)으로 미리 올려둔다 —
유튜브 서버가 그 시각에 공개하므로 Mac이 꺼져 있어도 올라간다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from settings import YOUTUBE_TOKEN, get_logger

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
VISIBILITY_MAP = {"공개": "public", "비공개": "private", "일부공개": "unlisted"}

ERROR_HINTS = {
    "quotaExceeded": "구글 API 일일 할당량 초과 (기본 하루 약 6개 업로드). 내일 다시 시도됩니다.",
    "dailyLimitExceeded": "구글 API 일일 할당량 초과. 내일 다시 시도됩니다.",
    "uploadLimitExceeded": "유튜브 채널의 24시간 업로드 한도 초과. 하루 뒤 다시 시도하세요.",
    "invalidTitle": "제목에 사용할 수 없는 문자가 있습니다.",
    "invalidDescription": "설명(캡션)에 사용할 수 없는 문자가 있습니다.",
    "forbidden": "권한 거부. setup/2_유튜브_연결.command 를 다시 실행해 보세요.",
}


class NotConnected(Exception):
    pass


@dataclass
class UploadResult:
    ok: bool
    message: str
    url: str = ""


class YouTubeUploader:
    def __init__(self):
        self.log = get_logger()
        self.service = None

    def _ensure_service(self):
        if self.service is not None:
            return
        if not YOUTUBE_TOKEN.exists():
            raise NotConnected()
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(str(YOUTUBE_TOKEN), SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                YOUTUBE_TOKEN.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise NotConnected()
        self.service = build("youtube", "v3", credentials=creds, cache_discovery=False)

    def upload(self, row, path: Path, publish_at: datetime | None = None) -> UploadResult:
        try:
            self._ensure_service()
        except NotConnected:
            return UploadResult(False, "유튜브 미연결 — setup/2_유튜브_연결.command 를 먼저 실행하세요.")
        except Exception as e:
            return UploadResult(False, f"유튜브 인증 오류: {e} (setup/2_유튜브_연결.command 재실행)")

        title = row.youtube_title()
        if not title:
            return UploadResult(False, "제목이 비어 있습니다. 엑셀의 제목 칸을 채워주세요.")

        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        tags = row.hashtags[:30]
        status = {
            "privacyStatus": VISIBILITY_MAP.get(row.visibility, "public"),
            "selfDeclaredMadeForKids": False,
        }
        # 서버 예약: 비공개로 올려두면 유튜브가 예약시각에 공개로 전환
        if publish_at is not None and row.visibility == "공개":
            status["privacyStatus"] = "private"
            status["publishAt"] = publish_at.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        body = {
            "snippet": {
                "title": title,
                "description": row.youtube_description(),
                "tags": tags,
                "categoryId": "22",
                "defaultLanguage": "ko",
            },
            "status": status,
        }
        media = MediaFileUpload(str(path), chunksize=8 * 1024 * 1024, resumable=True)
        try:
            request = self.service.videos().insert(
                part="snippet,status", body=body, media_body=media
            )
            self.log.info(f"유튜브 업로드 시작: {path.name}")
            response = None
            while response is None:
                progress, response = request.next_chunk()
                if progress:
                    self.log.info(f"  유튜브 업로드 중... {int(progress.progress() * 100)}%")
            video_id = response["id"]
            url = f"https://youtu.be/{video_id}"
            if publish_at is not None and row.visibility == "공개":
                msg = f"완료(예약 {publish_at:%m/%d %H:%M} 공개)"
            else:
                msg = "완료"
            self.log.info(f"유튜브 업로드 {msg}: {url}")
            return UploadResult(True, msg, url)
        except HttpError as e:
            reason = ""
            try:
                detail = json.loads(e.content.decode("utf-8"))
                err = detail.get("error", {}).get("errors", [{}])[0]
                reason = err.get("reason", "")
                msg = err.get("message", str(e))
            except Exception:
                msg = str(e)
            hint = ERROR_HINTS.get(reason, "")
            return UploadResult(False, f"{reason or 'API 오류'}: {hint or msg}")
        except Exception as e:
            return UploadResult(False, f"업로드 오류: {e}")
