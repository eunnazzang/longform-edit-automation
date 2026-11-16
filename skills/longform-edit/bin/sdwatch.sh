#!/bin/bash
# launchd(StartOnMount)가 볼륨이 마운트될 때마다 부른다. 카메라·녹음기 카드면 알림만 띄운다(복사는 하지 않음).
HERE="$(cd -P "$(dirname "$0")" && pwd)"
sleep 3
OUT="$("$HERE/lf" sd_backup --list 2>/dev/null | grep '^/Volumes/')"
[ -n "$OUT" ] || exit 0
SEEN="${LONGFORM_HOME:-$HOME/.longform-edit}/sd_seen.txt"
touch "$SEEN"
NEW="$(echo "$OUT" | cut -f1 | grep -vxF -f "$SEEN")"
[ -n "$NEW" ] || exit 0
echo "$OUT" | cut -f1 > "$SEEN"
NAMES="$(echo "$NEW" | xargs -I{} basename {} | paste -sd ', ' -)"
osascript -e "display notification \"Claude Code에 'SD카드 백업해줘'라고 하면 프로젝트 폴더로 백업해요.\" with title \"촬영 카드 감지: $NAMES\" sound name \"Glass\""
