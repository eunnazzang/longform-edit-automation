"""transcribe.py의 단어 json → 사람이 다듬을 전사본 초안.
사용: python3 transcript_lines.py <words.json> <출력.txt> [--gap 0.35] [--offset 0]
한 줄 형식: [mm:ss] ?: 대사   (화자는 '?'로 두고 화면 시트·클로즈업으로 채운다)
단어 사이 간격이 --gap초보다 길거나 문장부호(. ? !)로 끝나면 줄을 나눈다.
"""
from __future__ import annotations
import argparse, json


def tc(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("words"); ap.add_argument("out")
    ap.add_argument("--gap", type=float, default=0.35)
    ap.add_argument("--offset", type=float, default=0.0, help="마스터 타임 보정(초)")
    a = ap.parse_args()
    words = json.load(open(a.words, encoding="utf-8"))
    lines, cur, last_end = [], [], None
    for s, e, t in words:
        if cur and (s - last_end > a.gap or cur[-1][2].rstrip().endswith((".", "?", "!"))):
            lines.append(cur); cur = []
        cur.append((s, e, t)); last_end = e
    if cur:
        lines.append(cur)
    with open(a.out, "w", encoding="utf-8") as f:
        for g in lines:
            f.write(f"[{tc(g[0][0] + a.offset)}] ?: {' '.join(w[2].strip() for w in g)}\n")
    print(f"{len(lines)}줄 → {a.out}")


if __name__ == "__main__":
    main()
