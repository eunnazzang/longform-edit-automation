#!/bin/bash
# 최초 1회: 파이썬 환경 구성 + 폴더/엑셀 템플릿 생성
cd "$(dirname "$0")/.." || exit 1
echo "======================================"
echo " 자동 업로드 - 초기 설정"
echo "======================================"

PY=$(command -v python3)
if [ -z "$PY" ]; then
  echo "python3 를 찾을 수 없습니다. https://www.python.org 에서 설치 후 다시 실행하세요."
  read -r -p "엔터를 누르면 닫힙니다..."
  exit 1
fi
echo "파이썬: $($PY --version)"

if [ ! -d ".venv" ]; then
  echo "가상환경 생성 중..."
  "$PY" -m venv .venv || exit 1
fi

echo "필요 패키지 설치 중 (1-2분)..."
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt || {
  echo "패키지 설치 실패. 인터넷 연결을 확인하세요."; read -r -p "엔터..."; exit 1;
}

echo "폴더와 엑셀 템플릿 생성 중..."
./.venv/bin/python engine/make_excel.py

# 인스타 업로드 안정성을 위한 cloudflared (선택)
if [ ! -f "bin/cloudflared" ] && ! command -v cloudflared >/dev/null 2>&1; then
  echo ""
  echo "[선택] 인스타 업로드용 임시 URL 도구 'cloudflared' 를 설치할까요?"
  echo "  - 출처: Cloudflare 공식 GitHub 릴리스 (약 17MB)"
  echo "  - 설치하지 않아도 내장 대체 방식(localhost.run)으로 동작하지만,"
  echo "    cloudflared 쪽이 더 안정적입니다."
  read -r -p "설치하시겠습니까? (y/n): " REPLY
  if [ "$REPLY" = "y" ] || [ "$REPLY" = "Y" ]; then
    mkdir -p bin
    ARCH=$(uname -m)
    if [ "$ARCH" = "arm64" ]; then CF_ARCH="arm64"; else CF_ARCH="amd64"; fi
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-${CF_ARCH}.tgz"
    echo "다운로드 중: $URL"
    curl -L --fail -o bin/cloudflared.tgz "$URL" && \
      tar -xzf bin/cloudflared.tgz -C bin && rm -f bin/cloudflared.tgz && \
      chmod +x bin/cloudflared && echo "cloudflared 설치 완료 (bin/cloudflared)" || \
      echo "다운로드 실패 — 내장 대체 방식으로 동작합니다."
  fi
fi

echo ""
echo "초기 설정 완료. 다음 단계:"
echo "  setup/2_유튜브_연결.command"
echo "  setup/3_인스타_연결.command"
echo "  setup/4_틱톡_연결.command"
read -r -p "엔터를 누르면 닫힙니다..."
