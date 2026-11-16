#!/bin/bash
# 더블클릭하면 지금 바로 한 번 실행 (대기 중인 행을 모두 처리)
cd "$(dirname "$0")" || exit 1
if [ ! -x ".venv/bin/python" ]; then
  echo "먼저 setup/1_초기설정.command 를 실행하세요."; read -r -p "엔터..."; exit 1
fi
./.venv/bin/python engine/main.py
echo ""
read -r -p "끝났습니다. 엔터를 누르면 닫힙니다..."
