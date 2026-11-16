"""구성안·전사본 파서 (make_script.py / verify.py 공용)."""
from __future__ import annotations
import re

TC = r"(\d{1,2}:\d{2}(?:\.\d+)?)"
ITEM = re.compile(r"^(?:- |\|\s*\d+\s*\|\s*)" + TC + "~" + TC)
CARD = re.compile(r"^- ⏱\s*(\d+(?:\.\d+)?)초")
HEAD = re.compile(r"^## (\d+)\. (.+?)(?:\s*\{비율 ([\d.]+)\})?\s*$")
LINE = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*([^:]+?):\s*(.*)$")


def sec(t: str) -> float:
    parts = [float(p) for p in t.split(":")]
    v = 0.0
    for p in parts:
        v = v * 60 + p
    return v


def fmt(s: float) -> str:
    s = max(0, s)
    return f"{int(s // 60)}:{int(round(s % 60)):02d}" if round(s % 60) < 60 else f"{int(s // 60) + 1}:00"


def parse_plan(path: str, default_ratio: float = 0.86):
    """[{no, title, ratio, items:[(a,b,line)], cards:[sec]}]"""
    chapters = []
    cur = None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        m = HEAD.match(line)
        if m:
            cur = {"no": int(m.group(1)), "title": m.group(2).split(" (완성본")[0],
                   "ratio": float(m.group(3)) if m.group(3) else default_ratio,
                   "items": [], "cards": []}
            chapters.append(cur)
            continue
        if line.startswith("## "):
            cur = None  # 숏폼 후보·확인 필요 등은 계산에서 제외
            continue
        if cur is None:
            continue
        m = ITEM.match(line)
        if m:
            cur["items"].append((sec(m.group(1)), sec(m.group(2)), line))
            continue
        m = CARD.match(line)
        if m:
            cur["cards"].append(float(m.group(1)))
    return chapters


def parse_transcript(path: str):
    """[(start, end, speaker, text)] — end는 다음 줄 시작(마지막 줄은 파일 끝)."""
    rows = []
    for raw in open(path, encoding="utf-8"):
        m = LINE.match(raw.strip())
        if m:
            rows.append([sec(m.group(1)), None, m.group(2).strip(), m.group(3).strip()])
    for i, r in enumerate(rows):
        r[1] = rows[i + 1][0] if i + 1 < len(rows) else r[0] + 1.0
    return [tuple(r) for r in rows]


def is_staff(speaker: str) -> bool:
    return "스태프" in speaker or "제작" in speaker or speaker.startswith("(")


def lines_in(trans, a: float, b: float, min_overlap: float = 0.3):
    out = []
    for s, e, spk, txt in trans:
        if min(e, b) - max(s, a) >= min_overlap or (a <= s < b):
            out.append((s, e, spk, txt))
    return out
