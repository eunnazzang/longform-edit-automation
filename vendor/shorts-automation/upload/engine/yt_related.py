"""유튜브 쇼츠 '관련 동영상' 설정 자동화 (스튜디오 화면 조작).

공식 API에 관련 동영상 필드가 없어, 로그인된 스튜디오 프로필로 세부정보 화면을 직접 조작한다.
틱톡과 마찬가지로 화면 기반이라 유튜브가 UI를 개편하면 선택자 수정이 필요할 수 있다.
실패 시 logs/ 에 스크린샷이 남는다.

선택자는 2026-07 실측으로 확정:
 - 관련 동영상 트리거: #linked-video-editor-link
 - 선택 팝업 검색창 placeholder: '내 동영상 검색'
 - 저장 버튼: #save
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from settings import CONFIG_DIR, LOGS_DIR, get_logger
from yt_uploader import UploadResult

PROFILE_DIR = CONFIG_DIR / "youtube_studio_profile"
EDIT_URL = "https://studio.youtube.com/video/{vid}/edit"


class YouTubeStudio:
    def __init__(self, related_video_id: str, related_title: str):
        self.log = get_logger()
        self.related_id = related_video_id
        self.related_title = related_title
        self._pw = None
        self.context = None
        self.page = None

    def connected(self) -> bool:
        return PROFILE_DIR.exists() and any(PROFILE_DIR.iterdir())

    def _launch(self):
        if self.context:
            return
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        kwargs = dict(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1360, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
            locale="ko-KR",
        )
        try:
            self.context = self._pw.chromium.launch_persistent_context(channel="chrome", **kwargs)
        except Exception:
            self.context = self._pw.chromium.launch_persistent_context(**kwargs)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

    def _screenshot(self, tag: str) -> str:
        name = f"관련동영상오류_{tag}_{datetime.now():%H%M%S}.png"
        try:
            self.page.screenshot(path=str(LOGS_DIR / name))
            return f" (스크린샷: logs/{name})"
        except Exception:
            return ""

    def current_related_label(self, video_id: str) -> str:
        """이미 설정된 관련 동영상 라벨 조회 (설정 안 됐으면 '관련 동영상'만 반환)."""
        try:
            return self.page.locator("#linked-video-editor-link").first.inner_text().replace("\n", " ").strip()
        except Exception:
            return ""

    def set_related(self, video_id: str) -> UploadResult:
        """video_id 쇼츠의 관련 동영상을 self.related_id 로 설정."""
        if not self.connected():
            return UploadResult(False, "스튜디오 미연결 — setup/5_유튜브스튜디오_연결.command 를 먼저 실행하세요.")
        try:
            self._launch()
        except Exception as e:
            return UploadResult(False, f"브라우저 실행 실패: {e}")

        page = self.page
        try:
            page.goto(EDIT_URL.format(vid=video_id), wait_until="domcontentloaded", timeout=60_000)
            time.sleep(7)
            if "accounts.google.com" in page.url or "/signin" in page.url:
                return UploadResult(False, "스튜디오 로그인이 풀렸습니다. setup/5_유튜브스튜디오_연결.command 재실행 필요.")

            trig = page.locator("#linked-video-editor-link").first
            if trig.count() == 0:
                return UploadResult(
                    False, "관련 동영상 항목이 없습니다(쇼츠로 인식 안 됐거나 UI 변경)."
                    + self._screenshot(f"항목_{video_id}"),
                )
            trig.scroll_into_view_if_needed()
            time.sleep(1)

            # 이미 원하는 롱폼으로 설정돼 있으면 건너뜀 (중복 저장 방지)
            if self.related_title[:12] in trig.inner_text():
                self.log.info(f"  이미 설정됨 — 건너뜀: {video_id}")
                return UploadResult(True, "이미설정됨", f"https://youtu.be/{video_id}")

            trig.click()
            time.sleep(2)

            search = page.get_by_placeholder("내 동영상 검색").first
            if search.count() == 0:
                return UploadResult(False, "선택 팝업 검색창을 찾지 못했습니다." + self._screenshot(f"팝업_{video_id}"))
            search.click()
            search.fill(self.related_title[:20])
            time.sleep(3)

            item = page.get_by_text(self.related_title, exact=True).first
            if item.count() == 0:
                item = page.get_by_text(self.related_title[:18], exact=False).first
            if item.count() == 0:
                return UploadResult(False, "선택 팝업에서 대상 영상을 찾지 못했습니다." + self._screenshot(f"검색_{video_id}"))
            item.scroll_into_view_if_needed()
            time.sleep(1)
            item.click()
            time.sleep(3)

            save = page.locator("#save").first
            if save.count() == 0 or not save.is_enabled():
                # 선택이 반영 안 돼 저장이 비활성 → 실패로 처리
                return UploadResult(False, "저장 버튼이 활성화되지 않았습니다(선택 미반영)." + self._screenshot(f"저장_{video_id}"))
            save.click()
            time.sleep(4)

            label = trig.inner_text()
            if self.related_title[:12] in label:
                self.log.info(f"  관련 동영상 설정 완료: {video_id} → {self.related_title[:20]}")
                return UploadResult(True, "관련동영상 설정완료", f"https://youtu.be/{video_id}")
            return UploadResult(False, "저장 후 라벨 확인 실패." + self._screenshot(f"확인_{video_id}"))
        except Exception as e:
            return UploadResult(False, f"관련 동영상 자동화 오류: {e}" + self._screenshot(f"예외_{video_id}"))

    def close(self):
        try:
            if self.context:
                self.context.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self.context = self._pw = self.page = None
