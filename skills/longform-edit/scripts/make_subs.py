#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""전사(마스터 타임)를 편집결정 타임라인 위의 자막으로 바꾼다.

사용:  make_subs.py 편집자료/편집결정.json 편집자료/전사.json --out 편집자료/자막.json
       [--max-chars 18] [--gap 0.35] [--keep-punct]
출력:  {"items": [{"start": 타임라인초, "end": …, "text": "…", "cut": 컷번호}, …]}
자동 분절 뒤에 반드시 사람이 읽듯이 통독하며 오인식·고유명사·분절을 고친다.
자막은 컷 경계를 넘지 않는다(점프컷 뒤에 앞 컷 말이 남지 않게).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import load_json, save_json, strip_punct, timeline  # noqa: E402

ENDERS = ("다", "요", "죠", "까", "네", ".", "?", "!")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("edl"); ap.add_argument("words")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-chars", type=int, default=18, help="자막 한 장 최대 글자 수(공백 제외)")
    ap.add_argument("--gap", type=float, default=0.35, help="이만큼 쉬면 새 자막")
    ap.add_argument("--keep-punct", action="store_true", help="문장부호를 지우지 않는다")
    a = ap.parse_args()

    edl = load_json(a.edl)
    words = load_json(a.words)
    items = []
    for c in timeline(edl):
        ws = [w for w in words if c["in"] <= (w[0] + w[1]) / 2 < c["out"]]
        line, start, last_end = [], None, None

        def flush():
            if not line:
                return
            text = " ".join(line)
            if not a.keep_punct:
                text = strip_punct(text)
            if text:
                s = c["t0"] + max(start - c["in"], 0)
                e = c["t0"] + min(last_end - c["in"], c["dur"])
                items.append({"start": round(s, 3), "end": round(max(e, s + 0.4), 3),
                              "text": text, "cut": c["idx"]})
            line.clear()

        for w0, w1, t in ws:
            n = len("".join(line + [t]).replace(" ", ""))
            if line and (w0 - last_end > a.gap or n > a.max_chars):
                flush()
            if not line:
                start = w0
            line.append(t)
            last_end = w1
            if t.endswith(ENDERS) and len("".join(line)) >= 6:
                flush()
        flush()

    # 짧은 틈은 메워서 깜빡임을 없앤다(같은 컷 안에서만)
    for p, q in zip(items, items[1:]):
        if p["cut"] == q["cut"] and 0 < q["start"] - p["end"] < 0.3:
            p["end"] = q["start"]
        if p["end"] > q["start"]:
            p["end"] = q["start"]
    save_json({"items": items}, a.out)
    print(f"자막 {len(items)}개 → {a.out}")


if __name__ == "__main__":
    main()
