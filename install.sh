#!/bin/bash
# 롱폼 편집 자동화 설치 (macOS, Apple Silicon 권장)
#
#   bash install.sh [--root "<프로젝트들을 모아 둘 폴더>"] [--no-link] [--sd-watch] [--with-model]
#
#   --root        프로젝트 폴더 위치 (기본: 기존 설정 → 없으면 ~/Movies/롱폼제작)
#   --no-link     ~/.claude/skills 에 스킬을 연결하지 않는다 (/plugin 으로 설치했을 때)
#   --sd-watch    SD카드를 꽂으면 macOS 알림을 띄우는 백그라운드 감시를 켠다
#   --with-model  전사 모델(~1.5GB)을 지금 미리 받는다 (안 하면 첫 전사 때 자동으로 받음)
#
# 여러 번 돌려도 안전하다(이미 된 단계는 건너뛴다). 원본 영상이나 기존 스킬을 지우지 않는다 —
# 같은 이름의 스킬이 이미 있으면 ~/.longform-edit/backup/ 으로 옮겨 둔다.
set -u
REPO="$(cd "$(dirname "$0")" && pwd)"
LF_HOME="${LONGFORM_HOME:-$HOME/.longform-edit}"
ROOT=""; LINK=1; SDWATCH=0; MODEL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --no-link) LINK=0; shift ;;
    --sd-watch) SDWATCH=1; shift ;;
    --with-model) MODEL=1; shift ;;
    *) echo "모르는 옵션: $1"; exit 2 ;;
  esac
done
step() { printf "\n▶ %s\n" "$1"; }
ok()   { printf "  ✓ %s\n" "$1"; }
warn() { printf "  △ %s\n" "$1"; }
die()  { printf "  ✗ %s\n" "$1"; exit 1; }
mkdir -p "$LF_HOME" "$HOME/.local/bin"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

step "환경 확인"
OS="$(uname -s)"; ARCH="$(uname -m)"
[ "$OS" = "Darwin" ] || warn "macOS가 아니에요($OS). 대부분 동작하지만 전사는 faster-whisper를 따로 설치해야 해요."
[ "$ARCH" = "arm64" ] || warn "Apple Silicon이 아니에요($ARCH). mlx-whisper 대신 faster-whisper가 필요해요."
ok "$OS $ARCH"

step "파이썬"
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 /usr/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
[ -n "$PY" ] || die "Python 3.9 이상이 없어요. 터미널에서 'xcode-select --install' 을 실행한 뒤 다시 설치하세요."
ok "$($PY --version) ($PY)"
if [ ! -x "$LF_HOME/venv/bin/python" ]; then
  "$PY" -m venv "$LF_HOME/venv" || die "가상환경을 만들 수 없어요."
fi
VPY="$LF_HOME/venv/bin/python"
"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet -r "$REPO/requirements.txt" || die "패키지 설치 실패 — 인터넷 연결을 확인하세요."
if [ "$OS" = "Darwin" ] && [ "$ARCH" = "arm64" ]; then
  "$VPY" -m pip install --quiet "mlx-whisper>=0.4" || warn "mlx-whisper 설치 실패 — 전사가 안 될 수 있어요."
fi
ok "파이썬 패키지 ($LF_HOME/venv)"

step "ffmpeg"
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  ok "$(ffmpeg -version | head -1 | cut -c1-40)"
else
  if command -v brew >/dev/null 2>&1 && [ -w "$(brew --prefix)/bin" ]; then
    brew install ffmpeg && ok "brew 로 설치"
  fi
  if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    # Homebrew가 없거나 권한이 없으면 static-ffmpeg 패키지의 정적 빌드를 ~/.local/bin 에 연결한다
    "$VPY" -m pip install --quiet static-ffmpeg && \
    "$VPY" - <<'EOF'
import os, static_ffmpeg.run as r
ff, fp = r.get_or_fetch_platform_executables_else_raise()
b = os.path.expanduser("~/.local/bin")
for src, name in ((ff, "ffmpeg"), (fp, "ffprobe")):
    dst = os.path.join(b, name)
    if os.path.lexists(dst):
        os.remove(dst)
    os.symlink(src, dst)
print("  ✓ 정적 빌드 연결:", b)
EOF
    command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg 설치 실패. https://ffmpeg.org/download.html 에서 받아 ~/.local/bin 에 넣어 주세요."
    if ! grep -q '.local/bin' "$HOME/.zshrc" 2>/dev/null; then
      echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc"; ok "~/.zshrc 에 PATH 추가"
    fi
  fi
fi

step "기본 자막 폰트 (프리텐다드)"
mkdir -p "$LF_HOME/fonts"
if [ ! -f "$LF_HOME/fonts/Pretendard-Bold.otf" ]; then
  TMP="$(mktemp -d)"
  if curl -fsSL -o "$TMP/p.zip" "https://github.com/orioncactus/pretendard/releases/download/v1.3.9/Pretendard-1.3.9.zip"; then
    unzip -q -j "$TMP/p.zip" 'public/static/Pretendard-*.otf' -d "$LF_HOME/fonts" && ok "받음 → $LF_HOME/fonts"
  else
    warn "프리텐다드를 받지 못했어요. https://github.com/orioncactus/pretendard 에서 받아 $LF_HOME/fonts 에 넣어 주세요."
  fi
  rm -rf "$TMP"
else
  ok "이미 있음"
fi
if [ "$OS" = "Darwin" ] && [ -f "$LF_HOME/fonts/Pretendard-Bold.otf" ]; then
  mkdir -p "$HOME/Library/Fonts"
  for f in "$LF_HOME"/fonts/Pretendard-*.otf; do
    [ -f "$HOME/Library/Fonts/$(basename "$f")" ] || cp "$f" "$HOME/Library/Fonts/"
  done
  ok "macOS 서체에도 설치 (프리미어·파이널컷에서 같은 폰트로 보이게)"
fi

step "쇼츠 제작 도구"
FS="$REPO/vendor/shorts-automation/shorts"
if [ "$OS" = "Darwin" ] && [ ! -x "$FS/facescan" ]; then
  if command -v swiftc >/dev/null 2>&1; then
    swiftc -O "$FS/facescan.swift" -o "$FS/facescan" 2>/dev/null && ok "facescan 컴파일" || warn "facescan 컴파일 실패(쇼츠 얼굴 추적만 영향)"
  else
    warn "swiftc 없음 — 쇼츠 얼굴 추적을 쓰려면 'xcode-select --install' 후 다시 실행"
  fi
else
  ok "준비됨"
fi

step "설정"
CFG="$LF_HOME/config.json"
if [ -z "$ROOT" ] && [ -f "$CFG" ]; then
  ROOT="$("$VPY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("projects_root",""))' "$CFG")"
fi
[ -n "$ROOT" ] || ROOT="$HOME/Movies/롱폼제작"
ROOT="${ROOT/#\~/$HOME}"
mkdir -p "$ROOT"
[ -f "$ROOT/피드백기록.md" ] || cp "$REPO/prompts/피드백기록_템플릿.md" "$ROOT/피드백기록.md"
"$VPY" - "$CFG" "$ROOT" "$REPO" <<'EOF'
import json, os, sys
p, root, repo = sys.argv[1:]
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg.update(projects_root=root, feedback_log=os.path.join(root, "피드백기록.md"), repo=repo)
json.dump(cfg, open(p, "w"), ensure_ascii=False, indent=2)
EOF
ok "프로젝트 폴더: $ROOT"

if [ $LINK -eq 1 ]; then
  step "Claude Code 에 스킬 연결"
  mkdir -p "$HOME/.claude/skills" "$LF_HOME/backup"
  for s in longform-edit shorts-maker; do
    dst="$HOME/.claude/skills/$s"; src="$REPO/skills/$s"
    if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then ok "$s (이미 연결됨)"; continue; fi
    if [ -e "$dst" ] || [ -L "$dst" ]; then
      b="$LF_HOME/backup/${s}_$(date +%Y%m%d%H%M%S)"; mv "$dst" "$b"; warn "기존 $s 를 $b 로 옮겼어요"
    fi
    ln -s "$src" "$dst" && ok "$s → $dst"
  done
fi

if [ $SDWATCH -eq 1 ] && [ "$OS" = "Darwin" ]; then
  step "SD카드 감시 (꽂으면 알림)"
  PL="$HOME/Library/LaunchAgents/com.longform-edit.sdwatch.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PL" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.longform-edit.sdwatch</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$REPO/skills/longform-edit/bin/sdwatch.sh</string></array>
  <key>StartOnMount</key><true/>
</dict></plist>
EOF
  launchctl unload "$PL" 2>/dev/null; launchctl load "$PL" && ok "켜짐 (끄기: launchctl unload \"$PL\")"
fi

if [ $MODEL -eq 1 ] && [ "$ARCH" = "arm64" ]; then
  step "전사 모델 미리 받기 (~1.5GB)"
  "$VPY" -c 'from huggingface_hub import snapshot_download as d; d("mlx-community/whisper-large-v3-turbo")' && ok "완료"
fi

step "점검"
"$REPO/skills/longform-edit/bin/lf" doctor
echo
echo "설치 끝. Claude Code를 새로 열고 \"롱폼 편집해줘\" 라고 하면 시작해요."
