"""구성안 순서대로 전사 줄을 뽑아 예상 스크립트를 만든다.
사용: python3 make_script.py <구성안.md> <전사본.txt> <출력.txt>
완성본 시각 = 원본 구간 길이 × 장 비율(기본 0.86, 제목의 {비율 x}로 바꿈) + ⏱ 카드 길이
"""
from __future__ import annotations
import sys
from plan_parse import parse_plan, parse_transcript, lines_in, is_staff, fmt


def main():
    plan, trans_path, out = sys.argv[1:4]
    chapters = parse_plan(plan)
    trans = parse_transcript(trans_path)
    t = 0.0
    w = []
    for ch in chapters:
        w.append(f"\n===== {ch['no']}. {ch['title']}  (완성본 {fmt(t)}~) =====")
        for c in ch["cards"]:
            w.append(f"[{fmt(t)}] (카드 {c:g}초 — 자막·그래픽)")
            t += c
        for a, b, _ in ch["items"]:
            w.append(f"\n[{fmt(t)}] (원본 {fmt(a)}~{fmt(b)})")
            for s, e, spk, txt in lines_in(trans, a, b):
                if is_staff(spk):
                    continue
                w.append(f"{spk}: {txt}")
            t += (b - a) * ch["ratio"]
    w.insert(0, f"# 예상 스크립트 — 추정 총 길이 {fmt(t)}  (구성안: {plan.split('/')[-1]})")
    open(out, "w", encoding="utf-8").write("\n".join(w) + "\n")
    print(f"저장: {out}  /  추정 총 길이 {fmt(t)}")


if __name__ == "__main__":
    main()
