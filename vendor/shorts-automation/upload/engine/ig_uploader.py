"""인스타그램 릴스 업로더 (공식 Instagram API with Instagram Login).
영상은 공개 URL로만 전달 가능 → tunnel.py 가 업로드 순간에만 임시 주소를 만든다.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from settings import INSTAGRAM_TOKEN, get_logger
from yt_uploader import UploadResult

GRAPH = "https://graph.instagram.com"
CAPTION_LIMIT = 2200

ERROR_HINTS = {
    190: "토큰이 만료되었거나 무효입니다. setup/3_인스타_연결.command 를 다시 실행하세요.",
    9: "인스타 API 게시 한도(24시간 내 최대 횟수) 초과. 내일 다시 시도됩니다.",
    4: "요청이 너무 잦습니다(레이트리밋). 다음 실행 때 다시 시도됩니다.",
    2207026: "영상 형식 문제. MP4(H.264 + AAC), 9:16 세로 영상인지 확인하세요.",
}


class InstagramUploader:
    def __init__(self, config: dict):
        self.log = get_logger()
        self.version = config.get("instagram_api_version", "v23.0")
        self.store: dict | None = None
        if INSTAGRAM_TOKEN.exists():
            try:
                self.store = json.loads(INSTAGRAM_TOKEN.read_text(encoding="utf-8"))
            except Exception:
                self.store = None

    # ---------- 토큰 ----------
    def _save_store(self):
        INSTAGRAM_TOKEN.write_text(
            json.dumps(self.store, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def maybe_refresh_token(self):
        """장기 토큰(60일)을 발급 7일 후부터는 실행 때마다 갱신해 사실상 무기한 유지."""
        if not self.store:
            return
        try:
            obtained = datetime.fromisoformat(self.store.get("obtained_at", "2000-01-01T00:00:00"))
        except ValueError:
            obtained = datetime(2000, 1, 1)
        if datetime.now() - obtained < timedelta(days=7):
            return
        try:
            r = requests.get(
                f"{GRAPH}/refresh_access_token",
                params={
                    "grant_type": "ig_refresh_token",
                    "access_token": self.store["access_token"],
                },
                timeout=30,
            )
            data = r.json()
            if "access_token" in data:
                self.store["access_token"] = data["access_token"]
                self.store["obtained_at"] = datetime.now().isoformat()
                self._save_store()
                self.log.info("인스타 토큰 자동 갱신 완료 (60일 연장)")
            else:
                self.log.warning(f"인스타 토큰 갱신 실패(계속 진행): {data}")
        except Exception as e:
            self.log.warning(f"인스타 토큰 갱신 실패(계속 진행): {e}")

    # ---------- API ----------
    def _api_error(self, data: dict) -> str:
        err = data.get("error", {})
        code = err.get("code")
        hint = ERROR_HINTS.get(code, "")
        base = err.get("error_user_msg") or err.get("message", str(data))
        return f"{hint or base} (코드 {code})" if code else base

    def upload(self, row, path: Path, tunnel) -> UploadResult:
        if not self.store or "access_token" not in self.store:
            return UploadResult(False, "인스타 미연결 — setup/3_인스타_연결.command 를 먼저 실행하세요.")
        self.maybe_refresh_token()
        token = self.store["access_token"]
        user_id = self.store.get("user_id") or "me"

        if not tunnel.ensure_public():
            return UploadResult(
                False,
                "임시 공개 URL 생성 실패. 인터넷 연결을 확인하거나 "
                "setup/1_초기설정.command 에서 cloudflared 를 설치하세요.",
            )
        video_url = tunnel.register(path)
        self.log.info(f"인스타 임시 영상 주소: {video_url}")
        if not tunnel.verify(video_url, path):
            return UploadResult(False, "임시 공개 URL 접속 확인 실패. 다음 실행 때 다시 시도됩니다.")

        caption = row.caption_for("인스타")[:CAPTION_LIMIT]

        # 1) 미디어 컨테이너 생성
        try:
            r = requests.post(
                f"{GRAPH}/{self.version}/{user_id}/media",
                data={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption,
                    "share_to_feed": "true",
                    "access_token": token,
                },
                timeout=60,
            )
            data = r.json()
        except Exception as e:
            return UploadResult(False, f"인스타 API 접속 오류: {e}")
        if "id" not in data:
            return UploadResult(False, f"컨테이너 생성 실패: {self._api_error(data)}")
        container_id = data["id"]
        self.log.info(f"인스타 컨테이너 생성됨: {container_id} (영상 처리 대기)")

        # 2) 영상 처리 완료 대기 (Meta가 영상을 받아가 인코딩)
        status = ""
        for _ in range(100):  # 최대 약 10분
            time.sleep(6)
            try:
                r = requests.get(
                    f"{GRAPH}/{self.version}/{container_id}",
                    params={"fields": "status_code,status", "access_token": token},
                    timeout=30,
                )
                st = r.json()
            except Exception:
                continue
            status = st.get("status_code", "")
            if status == "FINISHED":
                break
            if status in ("ERROR", "EXPIRED"):
                return UploadResult(False, f"인스타 영상 처리 실패: {st.get('status', status)}")
        if status != "FINISHED":
            return UploadResult(False, "인스타 영상 처리 시간 초과(10분). 다음 실행 때 다시 시도됩니다.")

        # 3) 게시
        try:
            r = requests.post(
                f"{GRAPH}/{self.version}/{user_id}/media_publish",
                data={"creation_id": container_id, "access_token": token},
                timeout=60,
            )
            data = r.json()
        except Exception as e:
            return UploadResult(False, f"게시 요청 오류: {e}")
        if "id" not in data:
            return UploadResult(False, f"게시 실패: {self._api_error(data)}")
        media_id = data["id"]

        # 4) 게시물 링크 조회 (실패해도 업로드 자체는 성공)
        url = "https://www.instagram.com/"
        try:
            r = requests.get(
                f"{GRAPH}/{self.version}/{media_id}",
                params={"fields": "permalink", "access_token": token},
                timeout=30,
            )
            url = r.json().get("permalink", url)
        except Exception:
            pass
        self.log.info(f"인스타 업로드 완료: {url}")
        return UploadResult(True, "완료", url)
