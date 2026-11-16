"""유튜브 최초 연결 — 구글 OAuth 로그인 (브라우저가 열림)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

from settings import YOUTUBE_CLIENT_SECRET, YOUTUBE_TOKEN, ensure_dirs  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

GUIDE = """
--------------------------------------------------------------------
[준비물 없음] config/client_secret.json 파일이 아직 없습니다.

아래 순서대로 한 번만 만들어 주세요 (약 10분):

 1. https://console.cloud.google.com 접속 → 구글 로그인
 2. 상단 프로젝트 선택 → "새 프로젝트" → 이름: auto-upload → 만들기
 3. 왼쪽 메뉴 "API 및 서비스" → "라이브러리" → "YouTube Data API v3" 검색 → 사용 설정
 4. "API 및 서비스" → "OAuth 동의 화면"
    - User Type: 외부 → 만들기
    - 앱 이름: auto-upload / 이메일 입력 → 저장
    - 범위, 테스트 사용자는 건너뛰고 저장
    - 중요: 동의 화면 완성 후 "앱 게시" (게시 상태를 '프로덕션'으로)
      → 테스트 상태로 두면 로그인이 7일마다 풀립니다.
 5. "API 및 서비스" → "사용자 인증 정보" → "+ 사용자 인증 정보 만들기"
    → "OAuth 클라이언트 ID" → 유형: 데스크톱 앱 → 만들기
 6. 만들어진 클라이언트 오른쪽 다운로드 버튼 → JSON 다운로드
 7. 다운로드한 파일 이름을 client_secret.json 으로 바꿔서
    이 프로젝트의 config 폴더에 넣기:
    {dest}

넣은 뒤 이 스크립트(2_유튜브_연결.command)를 다시 실행하세요.
--------------------------------------------------------------------
"""


def main() -> int:
    ensure_dirs()
    if not YOUTUBE_CLIENT_SECRET.exists():
        print(GUIDE.format(dest=YOUTUBE_CLIENT_SECRET))
        return 1

    from google_auth_oauthlib.flow import InstalledAppFlow

    print("브라우저가 열립니다. 업로드할 유튜브 채널의 구글 계정으로 로그인하세요.")
    print("'확인되지 않은 앱' 경고가 나오면: 고급 → 이동(안전하지 않음) 을 누르면 됩니다.")
    print("(본인이 방금 만든 앱이라 안전합니다.)\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(YOUTUBE_CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    YOUTUBE_TOKEN.write_text(creds.to_json(), encoding="utf-8")

    print("\n유튜브 연결 완료. 토큰 저장 위치:", YOUTUBE_TOKEN)
    print("\n[중요 안내] 새로 만든 구글 API 프로젝트는 유튜브 심사(무료) 전까지")
    print("API로 올린 영상이 '비공개(잠김)'로 제한될 수 있습니다.")
    print("첫 영상을 하나 올려보고 공개로 잘 올라가는지 확인하세요.")
    print("잠김이 뜨면 아래 폼으로 심사를 신청하면 됩니다 (개인 사용 목적, 보통 며칠 내 승인):")
    print("https://support.google.com/youtube/contact/yt_api_form")
    return 0


if __name__ == "__main__":
    sys.exit(main())
