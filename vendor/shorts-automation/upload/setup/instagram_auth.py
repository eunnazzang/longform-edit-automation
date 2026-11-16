"""인스타그램 최초 연결 — Meta 개발자 앱에서 발급한 장기 토큰을 등록."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

import requests  # noqa: E402

from settings import INSTAGRAM_TOKEN, ensure_dirs, load_config  # noqa: E402

GUIDE = """
--------------------------------------------------------------------
인스타그램 연결 준비 (한 번만, 약 15분)

 0. 인스타 계정이 '프로페셔널 계정'(비즈니스 또는 크리에이터)이어야 합니다.
    인스타 앱 → 프로필 → 설정 → 계정 유형 및 도구 → 프로페셔널 계정으로 전환

 1. https://developers.facebook.com 접속 → 인스타에 연결된 페이스북/메타 계정으로 로그인
 2. "내 앱" → "앱 만들기" → 사용 사례: "기타" → 앱 유형: "비즈니스" → 이름 아무거나
 3. 앱 대시보드 → 제품 추가에서 "Instagram" 찾기 → 설정
 4. 왼쪽 메뉴 Instagram → "API setup with Instagram login"
    → 1단계에서 "Add account" 로 본인 인스타 계정 로그인/연결
 5. 연결된 계정 옆의 "Generate token" 버튼 → 인스타 로그인 승인
    → 나오는 긴 토큰 문자열 전체 복사
 6. 아래 입력창에 붙여넣기

참고: 앱을 심사에 제출할 필요 없습니다. 본인 계정은 개발 모드에서 바로 사용 가능합니다.
--------------------------------------------------------------------
"""


def main() -> int:
    ensure_dirs()
    config = load_config()
    version = config.get("instagram_api_version", "v23.0")
    print(GUIDE)

    token = input("장기 액세스 토큰 붙여넣기: ").strip()
    if not token:
        print("토큰이 비어 있습니다. 다시 실행하세요.")
        return 1

    print("\n토큰 확인 중...")
    try:
        r = requests.get(
            f"https://graph.instagram.com/{version}/me",
            params={"fields": "user_id,username,account_type", "access_token": token},
            timeout=30,
        )
        data = r.json()
    except Exception as e:
        print(f"접속 실패: {e}")
        return 1

    if "username" not in data:
        print("토큰 확인 실패. 응답:", json.dumps(data, ensure_ascii=False))
        print("토큰을 다시 발급받아 재시도하세요. (5번 단계의 Generate token)")
        return 1

    store = {
        "access_token": token,
        "user_id": str(data.get("user_id") or data.get("id") or ""),
        "username": data.get("username", ""),
        "account_type": data.get("account_type", ""),
        "obtained_at": datetime.now().isoformat(),
    }
    INSTAGRAM_TOKEN.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n인스타 연결 완료: @{store['username']} ({store['account_type']})")
    print("토큰은 60일짜리지만, 엔진이 실행될 때마다 자동 갱신하므로")
    print("주기적으로(최소 2달에 한 번) 업로드를 실행하는 한 다시 발급할 필요 없습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
