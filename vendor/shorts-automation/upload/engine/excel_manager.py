"""업로드목록.xlsx 읽기/쓰기. 사용자가 채우는 유일한 인터페이스."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from settings import PLATFORMS, RESULT_COLUMNS

SHEET_NAME = "업로드목록"
HEADERS = [
    "파일명", "제목", "캡션", "유튜브설명", "인스타캡션",
    "해시태그", "플랫폼", "예약시각", "공개설정",
    "상태", "유튜브결과", "인스타결과", "업로드시각", "메모",
]
# 유튜브설명/인스타캡션은 선택 사항 — 비워두면 '캡션'을 공통 사용
# 검토대기: 엔진이 새 영상을 자동 감지해 추가한 상태 — 캡션 검토 후 '대기'로 바꾸면 업로드됨
SKIP_STATUS = {"완료", "보류", "예시", "검토대기"}
DATE_FORMATS = [
    "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M",
    "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y.%m.%d",
]


@dataclass
class RowData:
    index: int
    filename: str = ""
    title: str = ""
    caption: str = ""
    yt_desc: str = ""        # 유튜브설명 (선택 — 비우면 캡션 사용)
    ig_caption: str = ""     # 인스타캡션 (선택)
    hashtags: list = field(default_factory=list)
    platforms: list = field(default_factory=list)
    schedule: datetime | None = None
    error: str = ""          # 행 자체의 입력 오류 (예약시각 형식, 플랫폼 오타 등)
    visibility: str = "공개"
    status: str = ""
    results: dict = field(default_factory=dict)

    def _with_tags(self, base: str) -> str:
        base = base.strip()
        if self.hashtags:
            base = (base + "\n\n" if base else "") + " ".join("#" + t for t in self.hashtags)
        return base.strip()

    def caption_for(self, platform: str) -> str:
        """플랫폼별 캡션. 전용 칸이 있으면 그걸, 없으면 캡션(없으면 제목) 사용."""
        override = {"인스타": self.ig_caption}.get(platform, "")
        return self._with_tags(override or self.caption or self.title)

    def youtube_title(self) -> str:
        t = self.title.strip()
        if not t and self.caption:
            t = self.caption.splitlines()[0].strip()
        t = t.replace("<", "(").replace(">", ")")
        return t[:100]

    def youtube_description(self) -> str:
        return self._with_tags(self.yt_desc or self.caption)[:4900]


def parse_hashtags(raw: str) -> list:
    if not raw:
        return []
    tokens = re.split(r"[,\s]+", str(raw).strip())
    return [t.lstrip("#").strip() for t in tokens if t.lstrip("#").strip()]


def parse_platforms(raw: str, default: str) -> tuple[list, str]:
    """플랫폼 문자열 → 리스트. (리스트, 오류메시지) 반환."""
    text = str(raw or "").strip() or str(default or "").strip() or "전체"
    if text in ("전체", "모두", "다", "all", "ALL"):
        return list(PLATFORMS), ""
    tokens = [t.strip() for t in re.split(r"[,/+\s]+", text) if t.strip()]
    alias = {
        "유튜브": "유튜브", "유투브": "유튜브", "youtube": "유튜브", "yt": "유튜브", "쇼츠": "유튜브",
        "인스타": "인스타", "인스타그램": "인스타", "instagram": "인스타", "릴스": "인스타", "ig": "인스타",
    }
    unsupported = {"틱톡", "tiktok", "tt"}
    out, bad = [], []
    for t in tokens:
        low = t.lower() if t.isascii() else t
        if low in unsupported:
            return out, "틱톡은 현재 미지원입니다 (유튜브/인스타만 가능)"
        key = alias.get(low)
        if key and key not in out:
            out.append(key)
        elif not key:
            bad.append(t)
    if bad:
        return out, f"플랫폼 값을 알 수 없음: {', '.join(bad)} (전체/유튜브/인스타 중 입력)"
    return out, ""


def parse_schedule(value) -> tuple[datetime | None, str]:
    if value is None or str(value).strip() == "":
        return None, ""
    if isinstance(value, datetime):
        return value, ""
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt), ""
        except ValueError:
            continue
    return None, f"예약시각 형식 오류: '{text}' (예: 2026-07-15 09:00)"


class ExcelManager:
    def __init__(self, path: Path, config: dict):
        self.path = path
        self.config = config
        self.wb = load_workbook(path)
        if SHEET_NAME not in self.wb.sheetnames:
            raise RuntimeError(f"엑셀에 '{SHEET_NAME}' 시트가 없습니다: {path}")
        self.ws = self.wb[SHEET_NAME]
        self.col = {}
        for c in range(1, self.ws.max_column + 1):
            name = str(self.ws.cell(row=1, column=c).value or "").strip()
            if name:
                self.col[name] = c
        missing = [h for h in HEADERS if h not in self.col]
        if missing:
            raise RuntimeError(f"엑셀 1행에 누락된 열: {', '.join(missing)}")

    def preflight_save(self) -> None:
        """엑셀이 열려 있으면(잠김) 업로드 전에 미리 중단한다."""
        try:
            self.wb.save(self.path)
        except PermissionError:
            raise RuntimeError(
                "업로드목록.xlsx 가 다른 프로그램(엑셀)에서 열려 있어 기록할 수 없습니다. "
                "엑셀을 닫고 다시 실행하세요."
            )

    def _get(self, r: int, header: str):
        return self.ws.cell(row=r, column=self.col[header]).value

    def set(self, r: int, header: str, value) -> None:
        self.ws.cell(row=r, column=self.col[header]).value = value

    def known_filenames(self) -> set:
        names = set()
        for r in range(2, self.ws.max_row + 1):
            v = str(self._get(r, "파일명") or "").strip()
            if v:
                names.add(v)
        return names

    def append_new_video(self, filename: str) -> None:
        """폴더에서 자동 감지된 새 영상을 '검토대기' 행으로 추가 (업로드는 안 함)."""
        r = self.ws.max_row + 1
        stem = filename.rsplit(".", 1)[0]
        self.set(r, "파일명", filename)
        self.set(r, "제목", stem)
        self.set(r, "플랫폼", "전체")
        self.set(r, "공개설정", self.config.get("default_visibility", "공개"))
        self.set(r, "상태", "검토대기")
        self.set(r, "메모", "자동 감지됨 — 캡션 확인 후 상태를 '대기'로 바꾸면 업로드됩니다")

    def save(self) -> None:
        self.wb.save(self.path)

    def iter_rows(self):
        for r in range(2, self.ws.max_row + 1):
            filename = str(self._get(r, "파일명") or "").strip()
            if not filename:
                continue
            row = RowData(index=r, filename=filename)
            row.title = str(self._get(r, "제목") or "").strip()
            row.caption = str(self._get(r, "캡션") or "").strip()
            row.yt_desc = str(self._get(r, "유튜브설명") or "").strip()
            row.ig_caption = str(self._get(r, "인스타캡션") or "").strip()
            row.hashtags = parse_hashtags(str(self._get(r, "해시태그") or ""))
            default_tags = parse_hashtags(self.config.get("default_hashtags", ""))
            for t in default_tags:
                if t not in row.hashtags:
                    row.hashtags.append(t)
            row.platforms, pf_err = parse_platforms(
                self._get(r, "플랫폼"), self.config.get("default_platforms", "전체")
            )
            row.schedule, sc_err = parse_schedule(self._get(r, "예약시각"))
            row.error = pf_err or sc_err
            row.visibility = str(self._get(r, "공개설정") or "").strip() or \
                self.config.get("default_visibility", "공개")
            row.status = str(self._get(r, "상태") or "").strip()
            for pf, col_name in RESULT_COLUMNS.items():
                row.results[pf] = str(self._get(r, col_name) or "").strip()
            yield row
