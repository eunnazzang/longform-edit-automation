"""구성안 ↔ 전사본 자동 검증.
사용: python3 verify.py <구성안.md> <전사본.txt> "<제외구간 mm:ss-mm:ss, …>"
"""
from __future__ import annotations
import sys
from plan_parse import parse_plan, parse_transcript, lines_in, is_staff, sec, fmt


def main():
    plan, trans_path = sys.argv[1:3]
    excl = []
    if len(sys.argv) > 3 and sys.argv[3].strip():
        for part in sys.argv[3].split(","):
            a, b = part.strip().split("-")
            excl.append((sec(a), sec(b)))
    chapters = parse_plan(plan)
    trans = parse_transcript(trans_path)
    t_end = trans[-1][0] if trans else 0
    problems = []
    used = []  # (a, b, 장번호)
    total = 0.0
    print("── 장별 예상 길이 ──")
    for ch in chapters:
        d = sum(ch["cards"]) + sum((b - a) * ch["ratio"] for a, b, _ in ch["items"])
        print(f"  {ch['no']}. {ch['title']}: {fmt(total)}~{fmt(total + d)}  ({d:.0f}초)")
        total += d
        for a, b, line in ch["items"]:
            tag = f"{ch['no']}장 {fmt(a)}~{fmt(b)}"
            if b <= a:
                problems.append(f"[역순/0초] {tag}")
            if a > t_end:
                problems.append(f"[전사 범위 밖] {tag} (전사 끝 {fmt(t_end)})")
            ls = [x for x in lines_in(trans, a, b) if not is_staff(x[2])]
            if not ls:
                problems.append(f"[전사 줄 없음] {tag}")
            for ea, eb in excl:
                if min(b, eb) - max(a, ea) > 0.05:
                    problems.append(f"[제외 구간 침범] {tag} ↔ 제외 {fmt(ea)}~{fmt(eb)}")
            for ua, ub, uch in used:
                if min(b, ub) - max(a, ua) > 0.05:
                    note = " — 콜드오픈 재사용(정상)" if 0 in (uch, ch["no"]) else ""
                    problems.append(f"[구간 겹침] {tag} ↔ {uch}장 {fmt(ua)}~{fmt(ub)}{note}")
            used.append((a, b, ch["no"]))
    print(f"  전체: {fmt(total)}")
    print("── 문제 ──")
    if not problems:
        print("  없음")
    for p in problems:
        print("  " + p)
    # 원본에서 아무 데도 안 쓴 구간(참고)
    body = sorted((a, b) for a, b, c in used if c != 0)
    gaps, cur = [], 0.0
    for a, b in body:
        if a - cur > 1.0:
            gaps.append((cur, a))
        cur = max(cur, b)
    if trans and trans[-1][1] - cur > 1.0:
        gaps.append((cur, trans[-1][1]))
    print("── 본편에서 안 쓴 원본 구간(참고) ──")
    print("  " + (", ".join(f"{fmt(a)}~{fmt(b)}" for a, b in gaps) or "없음"))


if __name__ == "__main__":
    main()
