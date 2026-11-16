#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
if [ ! -x ".venv/bin/python" ]; then
  echo "먼저 setup/1_초기설정.command 를 실행하세요."; read -r -p "엔터..."; exit 1
fi
./.venv/bin/python setup/youtube_auth.py
read -r -p "엔터를 누르면 닫힙니다..."
