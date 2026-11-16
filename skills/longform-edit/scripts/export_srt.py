#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""자막.json → SRT. 파이널컷·캡컷·프리미어(캡션 트랙)·다빈치에서 자막을 따로 불러올 때 쓴다.

사용:  export_srt.py 편집자료/자막.json --out "편집자료/<제목>_자막.srt" [--style Default]
       --style 을 주면 그 스타일 자막만(예: 강조 자막을 따로 뽑기). 안 주면 전부.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import load_json  # noqa: E402


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--style")
    a = ap.parse_args()
    items = load_json(a.subs)["items"]
    if a.style:
        items = [i for i in items if i.get("style", "Default") == a.style]
    with open(a.out, "w", encoding="utf-8") as f:
        for n, it in enumerate(sorted(items, key=lambda x: x["start"]), 1):
            f.write(f"{n}\n{srt_time(it['start'])} --> {srt_time(it['end'])}\n{it['text']}\n\n")
    print(f"자막 {len(items)}개 → {a.out}")


if __name__ == "__main__":
    main()
