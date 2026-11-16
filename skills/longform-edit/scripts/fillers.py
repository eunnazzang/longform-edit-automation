#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""전사에서 지울 후보(필러 '음·어', 말 반복, 다시 말하기, 긴 침묵)를 찾는다.

사용:  fillers.py 편집자료/전사/전사.json --out 편집자료/필러후보 [--pause 0.6] [--from 0 --to 9999]
출력:  필러후보.json  [{"type": "filler|repeat|restart|pause", "start": 마스터초, "end": …, "text": …}, …]
       필러후보.md    사람이 훑어보는 표 (타임코드 순)
컷편집(편집결정.json) 때 이 목록을 보고 컷 경계를 정한다. 자동으로 지우지는 않는다 —
'음'이 감탄·리액션으로 살아 있는 경우가 있으니 앞뒤 문맥을 보고 판단한다.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import load_json, save_json, strip_punct, ts  # noqa: E402

FILLERS = {"음", "어", "아", "으", "흠", "엄", "어어", "음음", "그", "저", "뭐", "막", "약간", "이제", "그니까",
           "그러니까", "근데", "어쨌든", "뭐지", "그게"}
STRONG = {"음", "어", "으", "흠", "엄", "어어", "음음", "아"}  # 거의 항상 지우는 것


def norm(t: str) -> str:
    return re.sub(r"[~\-…]+", "", strip_punct(t))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words")
    ap.add_argument("--out", required=True, help="출력 경로(확장자 없이)")
    ap.add_argument("--pause", type=float, default=0.6, help="이 이상 쉬면 침묵 후보")
    ap.add_argument("--from", dest="t0", type=float, default=0)
    ap.add_argument("--to", dest="t1", type=float, default=1e9)
    a = ap.parse_args()

    ws = [w for w in load_json(a.words) if a.t0 <= w[0] < a.t1]
    out = []
    for i, (s, e, t) in enumerate(ws):
        n = norm(t)
        if n in STRONG:
            out.append({"type": "filler", "start": s, "end": e, "text": t, "sure": True})
        elif n in FILLERS:
            out.append({"type": "filler", "start": s, "end": e, "text": t, "sure": False})
        if i and norm(ws[i - 1][2]) == n and len(n) >= 1 and s - ws[i - 1][1] < 1.0:
            out.append({"type": "repeat", "start": ws[i - 1][0], "end": ws[i - 1][1],
                        "text": f"{ws[i - 1][2]} {t}", "sure": True})
        if i and s - ws[i - 1][1] >= a.pause:
            out.append({"type": "pause", "start": ws[i - 1][1], "end": s,
                        "text": f"{s - ws[i - 1][1]:.1f}초", "sure": s - ws[i - 1][1] >= 1.2})
    # 다시 말하기: 2~4어절 구절이 8초 안에 그대로 다시 나오면 앞의 것이 NG일 가능성
    toks = [norm(w[2]) for w in ws]
    for k in (4, 3, 2):
        for i in range(len(ws) - k):
            ph = toks[i:i + k]
            if sum(len(x) for x in ph) < 4:
                continue
            for j in range(i + k, min(i + k + 25, len(ws) - k + 1)):
                if ws[j][0] - ws[i][0] > 8:
                    break
                if toks[j:j + k] == ph:
                    out.append({"type": "restart", "start": ws[i][0], "end": ws[j][0],
                                "text": " ".join(w[2] for w in ws[i:j + k]), "sure": False})
                    break
    out.sort(key=lambda r: (r["start"], r["type"]))
    save_json(out, a.out + ".json")
    names = {"filler": "필러", "repeat": "반복", "restart": "다시 말하기", "pause": "침묵"}
    with open(a.out + ".md", "w", encoding="utf-8") as f:
        f.write("# 지울 후보 (자동 탐지 — 문맥 보고 판단)\n\n| 마스터 TC | 종류 | 확실 | 내용 |\n|---|---|---|---|\n")
        for r in out:
            f.write(f"| {ts(r['start'])}~{ts(r['end'])} | {names[r['type']]} | {'●' if r['sure'] else '○'} | {r['text']} |\n")
    cnt = {k: sum(1 for r in out if r["type"] == k) for k in names}
    print("후보 " + ", ".join(f"{names[k]} {v}" for k, v in cnt.items()) + f" → {a.out}.md")


if __name__ == "__main__":
    main()
