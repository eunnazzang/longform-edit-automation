"""틱톡 업로더 — Chrome 자동 조작(Playwright) 방식.

틱톡 공식 API는 앱 심사를 통과하지 못하면 '나만 보기'로만 게시할 수 있어
개인/소규모 사용에는 사실상 쓸 수 없다. 그래서 로그인해 둔 Chrome 프로필로
틱톡 스튜디오 업로드 페이지를 직접 조작한다.

주의: 틱톡이 웹 화면을 개편하면 선택자 수정이 필요할 수 있다.
실패 시 logs/ 폴더에 스크린샷이 남는다.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from settings import LOGS_DIR, TIKTOK_PROFILE_DIR, get_logger
from yt_uploader import UploadResult

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=upload"
# data-e2e 우선, 그 외에는 버튼 텍스트 '정확히 일치'만 허용
# (부분 일치를 쓰면 사이드바 '게시물' 메뉴 등을 잘못 클릭한다)
POST_BUTTON_DATA_SELECTORS = [
    '[data-e2e="post_video_button"]',
    'button[data-e2e="upload-post"]',
]
POST_BUTTON_EXACT_NAMES = ["게시", "Post"]
# :visible — 숨겨진 동일 태그가 여럿 있어 보이는 것만 잡는다
CAPTION_SELECTORS = [
    '.public-DraftEditor-content[contenteditable="true"]:visible',
    'div[contenteditable="true"]:visible',
]
# 첫 업로드 등에서 뜨는 안내 팝업("자동 콘텐츠 검사를 켤까요?" 등)을 닫는 버튼들.
# 계정 설정을 바꾸지 않도록 취소/닫기 계열만 누른다.
MODAL_DISMISS_SELECTORS = [
    '[role="dialog"] button:has-text("취소")',
    '[role="dialog"] button:has-text("나중에")',
    '[role="dialog"] button:has-text("Cancel")',
    '[role="dialog"] button:has-text("Not now")',
    '[role="dialog"] [aria-label="닫기"]',
    '[role="dialog"] [aria-label="Close"]',
    '.TUXModal button:has-text("취소")',
    '.TUXModal [aria-label="닫기"]',
]


class TikTokUploader:
    def __init__(self):
        self.log = get_logger()
        self._pw = None
        self.context = None

    def connected(self) -> bool:
        return TIKTOK_PROFILE_DIR.exists() and any(TIKTOK_PROFILE_DIR.iterdir())

    def _launch(self):
        if self.context:
            return
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        TIKTOK_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        kwargs = dict(
            user_data_dir=str(TIKTOK_PROFILE_DIR),
            headless=False,
            viewport={"width": 1360, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
            locale="ko-KR",
        )
        try:
            self.context = self._pw.chromium.launch_persistent_context(channel="chrome", **kwargs)
        except Exception:
            # 시스템 Chrome 실행 실패 시 Playwright 내장 브라우저로 시도
            self.context = self._pw.chromium.launch_persistent_context(**kwargs)

    def _screenshot(self, page, tag: str) -> str:
        name = f"틱톡오류_{tag}_{datetime.now():%H%M%S}.png"
        try:
            page.screenshot(path=str(LOGS_DIR / name), full_page=False)
            return f" (스크린샷: logs/{name})"
        except Exception:
            return ""

    def _kill_tour_overlays(self, page) -> None:
        """첫 사용자용 기능 안내 투어(react-joyride)가 클릭을 가로채면 무력화한다.

        주의: DOM 요소를 삭제하면 React 앱 전체가 죽을 수 있다(실측).
        Escape → 건너뛰기 버튼 → 클릭 통과 처리(스타일만 변경) 순으로만 다룬다.
        """
        try:
            if page.locator("#react-joyride-portal, .react-joyride__overlay").count() == 0:
                return
        except Exception:
            return
        try:
            page.keyboard.press("Escape")
            time.sleep(1)
        except Exception:
            pass
        try:
            for sel in (
                '.react-joyride__tooltip button[data-action="skip"]',
                '.react-joyride__tooltip button[data-action="close"]',
                '.react-joyride__tooltip button:has-text("건너뛰기")',
                '.react-joyride__tooltip button:has-text("Skip")',
                '.react-joyride__tooltip [aria-label="Close"]',
                '#react-joyride-portal button:has-text("확인")',
            ):
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click(timeout=2000)
                    self.log.info("틱톡 화면 안내 투어 건너뜀")
                    time.sleep(1)
                    break
        except Exception:
            pass
        try:
            changed = page.evaluate(
                "() => { const els = document.querySelectorAll("
                "'#react-joyride-portal, .react-joyride__overlay');"
                " let n = 0; els.forEach(e => {"
                " if (e.style.pointerEvents !== 'none') { e.style.pointerEvents = 'none'; n++; }"
                " }); return n; }"
            )
            if changed:
                self.log.info(f"틱톡 안내 오버레이 클릭 통과 처리 ({changed}개)")
        except Exception:
            pass

    def _error_page_visible(self, page) -> bool:
        """틱톡 스튜디오 자체 오류 화면('문제가 발생했습니다') 감지."""
        try:
            return page.get_by_text("문제가 발생했습니다").count() > 0 or \
                page.get_by_text("Something went wrong").count() > 0
        except Exception:
            return False

    def _dismiss_modals(self, page, rounds: int = 4) -> None:
        """화면을 덮는 안내 팝업을 닫는다 (여러 개가 연달아 뜰 수 있어 반복)."""
        self._kill_tour_overlays(page)
        for _ in range(rounds):
            closed = False
            for sel in MODAL_DISMISS_SELECTORS:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        loc.click(timeout=3000)
                        self.log.info(f"틱톡 안내 팝업 닫음 ({sel})")
                        closed = True
                        time.sleep(1.5)
                        break
                except Exception:
                    continue
            if not closed:
                return

    def _find_caption_box(self, page):
        for sel in CAPTION_SELECTORS:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    return loc
            except Exception:
                continue
        return None

    def _find_enabled_post_button(self, page):
        candidates = [page.locator(sel).first for sel in POST_BUTTON_DATA_SELECTORS]
        candidates += [
            page.get_by_role("button", name=name, exact=True).first
            for name in POST_BUTTON_EXACT_NAMES
        ]
        for btn in candidates:
            try:
                if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                    if btn.get_attribute("aria-disabled") not in ("true",):
                        return btn
            except Exception:
                continue
        return None

    def _leave_dialog_visible(self, page) -> bool:
        """'끝낼까요?' 페이지 이탈 확인창이 떠 있는지 (= 잘못된 버튼을 눌렀다는 신호)."""
        try:
            return page.get_by_text("끝낼까요?").count() > 0 or \
                page.get_by_text("진행 상황 및 변경 사항이 저장되지").count() > 0
        except Exception:
            return False

    def _set_private(self, page) -> bool:
        """공개 범위를 '나만 보기'로 변경. 실패하면 False (게시 중단)."""
        try:
            for label in ("모든 사람", "Everyone"):
                trigger = page.get_by_text(label, exact=True)
                if trigger.count() > 0:
                    trigger.first.click()
                    time.sleep(1)
                    for target in ("나만 보기", "본인만", "Only you", "Only me"):
                        opt = page.get_by_text(target, exact=True)
                        if opt.count() > 0:
                            opt.first.click()
                            time.sleep(1)
                            return True
            return False
        except Exception:
            return False

    def upload(self, row, path: Path) -> UploadResult:
        if not self.connected():
            return UploadResult(False, "틱톡 미연결 — setup/4_틱톡_연결.command 를 먼저 실행하세요.")
        try:
            self._launch()
        except Exception as e:
            return UploadResult(False, f"브라우저 실행 실패: {e}")

        page = self.context.new_page()
        try:
            page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(5)

            if "/login" in page.url:
                return UploadResult(False, "틱톡 로그인이 풀렸습니다. setup/4_틱톡_연결.command 재실행 필요.")
            if self._error_page_visible(page):
                return UploadResult(
                    False, "틱톡 스튜디오 오류 화면(문제가 발생했습니다). 다음 실행 때 재시도됩니다.",
                )
            self._dismiss_modals(page)

            # 파일 선택
            file_input = page.wait_for_selector('input[type="file"]', state="attached", timeout=60_000)
            file_input.set_input_files(str(path))
            self.log.info(f"틱톡 영상 업로드 시작: {path.name}")

            # 편집 화면(캡션 입력창) 대기 — 안내 팝업이 덮고 있으면 닫으면서 기다린다
            caption_box = None
            deadline = time.time() + 180
            while time.time() < deadline:
                self._dismiss_modals(page)
                caption_box = self._find_caption_box(page)
                if caption_box:
                    break
                time.sleep(3)
            if not caption_box:
                return UploadResult(
                    False, "캡션 입력창을 찾지 못했습니다(화면 개편 가능성)."
                    + self._screenshot(page, "캡션창"),
                )
            time.sleep(3)

            # 캡션 입력 (기존 자동 입력된 파일명 지우고 새로 입력)
            self._dismiss_modals(page)
            caption_box.click(timeout=15_000)
            page.keyboard.press("Meta+A")
            page.keyboard.press("Backspace")
            time.sleep(0.5)
            page.keyboard.type(row.caption_for("틱톡"), delay=25)
            page.keyboard.press("Escape")  # 해시태그 추천 팝업 닫기
            time.sleep(1)

            # 비공개 요청 시 공개 범위 변경 (실패하면 게시하지 않음)
            if row.visibility == "비공개":
                if not self._set_private(page):
                    return UploadResult(
                        False,
                        "비공개 설정을 찾지 못해 게시를 중단했습니다(공개로 잘못 올라가는 것 방지)."
                        + self._screenshot(page, "비공개설정"),
                    )

            # 파일 업로드 완료 표시("업로드됨") 대기 — 그 전에는 게시 버튼을 찾지 않는다
            deadline = time.time() + 240
            uploaded_seen = False
            while time.time() < deadline:
                if self._error_page_visible(page):
                    return UploadResult(
                        False, "틱톡 스튜디오 오류 화면(문제가 발생했습니다). 다음 실행 때 재시도됩니다."
                        + self._screenshot(page, "오류화면"),
                    )
                try:
                    if page.get_by_text("업로드됨").count() > 0 or \
                            page.get_by_text("Uploaded").count() > 0:
                        uploaded_seen = True
                        break
                except Exception:
                    pass
                time.sleep(3)
            if uploaded_seen:
                self.log.info("틱톡 파일 업로드 완료 표시 확인")
            else:
                self.log.warning("'업로드됨' 표시를 못 찾음 — 게시 버튼 상태로 계속 진행")

            # 게시 버튼 활성화 대기 (최대 5분)
            btn = None
            deadline = time.time() + 300
            while time.time() < deadline:
                self._dismiss_modals(page)
                btn = self._find_enabled_post_button(page)
                if btn:
                    break
                time.sleep(5)
            if not btn:
                return UploadResult(
                    False, "게시 버튼이 활성화되지 않았습니다(영상 처리 지연 또는 화면 개편)."
                    + self._screenshot(page, "게시버튼"),
                )
            time.sleep(2)
            btn.click()
            self.log.info("틱톡 게시 버튼 클릭, 완료 확인 중...")
            time.sleep(3)
            if self._leave_dialog_visible(page):
                # 잘못된 버튼을 눌러 페이지 이탈 확인창이 뜬 경우 — 게시되지 않았음
                try:
                    page.get_by_role("button", name="취소", exact=True).first.click(timeout=5000)
                except Exception:
                    pass
                return UploadResult(
                    False, "게시 버튼 오클릭 감지(이탈 확인창) — 게시되지 않았습니다."
                    + self._screenshot(page, "오클릭"),
                )

            # 게시 완료 확인 (성공 모달 또는 콘텐츠 목록으로 이동)
            deadline = time.time() + 180
            while time.time() < deadline:
                if "/content" in page.url:
                    break
                found = False
                for text in ("게시되었습니다", "동영상을 게시했습니다", "게시됨", "has been posted", "Manage your posts"):
                    try:
                        if page.get_by_text(text).count() > 0:
                            found = True
                            break
                    except Exception:
                        pass
                if found:
                    break
                time.sleep(4)
            else:
                return UploadResult(
                    False, "게시 완료 확인 실패. 틱톡 스튜디오에서 게시 여부를 직접 확인하세요."
                    + self._screenshot(page, "완료확인"),
                )

            self.log.info("틱톡 업로드 완료")
            return UploadResult(True, "완료", "https://www.tiktok.com/tiktokstudio/content")
        except Exception as e:
            return UploadResult(False, f"틱톡 자동화 오류: {e}" + self._screenshot(page, "예외"))
        finally:
            try:
                page.close()
            except Exception:
                pass

    def close(self):
        try:
            if self.context:
                self.context.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self.context = None
        self._pw = None
