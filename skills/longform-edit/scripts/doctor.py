#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""설치 상태 점검.  사용: lf doctor   (문제가 있으면 종료 코드 1)"""
from __future__ import annotations

import importlib
import os
import platform
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import FFMPEG, FFPROBE, LF_HOME, config, default_font  # noqa: E402

REPO = os.environ.get("LONGFORM_REPO", os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))


def main():
    rows, bad = [], 0

    def check(name, ok, detail="", required=True):
        nonlocal bad
        if not ok and required:
            bad += 1
        rows.append(f"{'✓' if ok else ('✗' if required else '△')} {name}{' — ' + detail if detail else ''}")

    check("macOS Apple Silicon", platform.system() == "Darwin" and platform.machine() == "arm64",
          f"{platform.system()} {platform.machine()}", required=False)
    check("Python 3.9+", sys.version_info >= (3, 9), sys.version.split()[0])
    for exe in (FFMPEG, FFPROBE):
        p = shutil.which(exe) or (exe if os.path.exists(exe) else None)
        ver = ""
        if p:
            ver = subprocess.run([p, "-version"], capture_output=True, text=True).stdout.split("\n")[0][:60]
        check(os.path.basename(exe), bool(p), ver or "없음 — install.sh 다시 실행")
    for mod, req in (("numpy", True), ("scipy", True), ("PIL", True), ("yt_dlp", True), ("mlx_whisper", platform.machine() == "arm64"),
                     ("openpyxl", False), ("googleapiclient", False)):
        try:
            importlib.import_module(mod)
            check(f"파이썬 모듈 {mod}", True)
        except Exception as e:  # noqa: BLE001
            check(f"파이썬 모듈 {mod}", False, str(e)[:80], required=req)
    f = default_font("Bold")
    check("기본 자막 폰트 Pretendard", bool(f), f or "없음 — install.sh 다시 실행")
    cfg = config()
    root = os.path.expanduser(cfg["projects_root"])
    check("프로젝트 폴더", os.path.isdir(root), root)
    check("설정 파일", os.path.exists(os.path.join(LF_HOME, "config.json")), os.path.join(LF_HOME, "config.json"))
    link = os.path.expanduser("~/.claude/skills/longform-edit")
    check("Claude 스킬 연결 (~/.claude/skills/longform-edit)", os.path.exists(os.path.join(link, "SKILL.md")),
          os.path.realpath(link) if os.path.exists(link) else "없음(플러그인으로 설치했다면 정상)", required=False)
    fs = os.path.join(REPO, "vendor/shorts-automation/shorts/facescan")
    check("얼굴 스캔 도구(쇼츠용 facescan)", os.path.exists(fs), "" if os.path.exists(fs) else "Xcode 도구가 있으면 install.sh가 컴파일", required=False)
    hf = os.path.expanduser("~/.cache/huggingface/hub/models--mlx-community--whisper-large-v3-turbo")
    check("전사 모델(첫 전사 때 자동 다운로드 ~1.5GB)", os.path.isdir(hf), "", required=False)
    print("\n".join(rows))
    print(f"\n{'준비 완료' if not bad else f'필수 항목 {bad}개 문제'}  (✓ 정상 · △ 선택 · ✗ 필수 문제)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
