"""업로드목록.xlsx 템플릿 + 폴더 구조 생성. 이미 있으면 건드리지 않는다."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from excel_manager import HEADERS, SHEET_NAME
from settings import EXCEL_PATH, PENDING_DIR, ensure_dirs, load_config

COLUMN_WIDTHS = {
    "파일명": 30, "제목": 40, "캡션": 45, "유튜브설명": 45, "인스타캡션": 45,
    "해시태그": 30, "플랫폼": 14,
    "예약시각": 18, "공개설정": 10, "상태": 10,
    "유튜브결과": 40, "인스타결과": 40, "업로드시각": 18, "메모": 25,
}

GUIDE_LINES = [
    ("자동 업로드 — 엑셀 작성법", True),
    ("", False),
    ("1. 영상 파일을 '업로드대기' 폴더에 넣는다.", False),
    ("2. 이 파일의 '업로드목록' 시트에 한 줄씩 적는다.", False),
    ("3. '업로드 실행.command' 를 더블클릭하거나, 자동실행을 켜두면 알아서 올라간다.", False),
    ("4. 업로드가 끝나면 상태/결과 칸이 자동으로 채워지고, 영상은 '업로드완료' 폴더로 이동한다.", False),
    ("", False),
    ("각 칸 설명", True),
    ("파일명    : 업로드대기 폴더 안의 영상 파일 이름 (예: 쇼츠1.mp4 — 확장자까지 정확히)", False),
    ("제목      : 유튜브 제목 (인스타/틱톡은 캡션이 비어 있을 때 이 제목을 캡션으로 사용)", False),
    ("캡션      : 공통 본문 (아래 플랫폼별 칸이 비어 있을 때 사용)", False),
    ("유튜브설명/인스타캡션 : 플랫폼별로 다르게 쓰고 싶을 때만 채우는 선택 칸", False),
    ("해시태그  : 띄어쓰기로 구분 (예: #쇼츠 #영어공부 — # 은 붙여도 되고 안 붙여도 됨)", False),
    ("플랫폼    : 전체 / 유튜브 / 인스타 / 틱톡 / 조합(쉼표로: 유튜브,인스타)", False),
    ("예약시각  : 비워두면 즉시. 적으면 그 시각 이후 첫 실행 때 업로드 (예: 2026-07-15 09:00)", False),
    ("            자동실행이 켜져 있어야 예약이 의미가 있다 (30분 간격으로 확인).", False),
    ("공개설정  : 공개 / 비공개 / 일부공개 (인스타는 항상 공개로 게시됨 — API 제한)", False),
    ("상태      : 비워두거나 '대기' 로 두면 처리 대상. '보류' 로 적으면 건너뜀.", False),
    ("            나머지 값(처리중/완료/실패/일부실패)은 시스템이 자동 기록.", False),
    ("", False),
    ("자주 하는 실수", True),
    ("- 파일명 오타 (실제 파일 이름과 다르면 '파일 없음' 실패)", False),
    ("- 엑셀을 열어둔 채 실행 → 기록을 못 해서 실행이 중단됨. 실행 전에 엑셀을 닫을 것.", False),
    ("- 실패한 행은 사유를 고치고 그대로 두면 다음 실행 때 자동 재시도 (성공한 플랫폼은 중복 업로드 안 됨)", False),
]


def make(path=EXCEL_PATH) -> bool:
    ensure_dirs()
    load_config()
    marker = PENDING_DIR / "여기에 영상 파일을 넣으세요.txt"
    if not marker.exists():
        marker.write_text(
            "이 폴더에 업로드할 쇼츠 영상(mp4/mov)을 넣고,\n"
            "업로드목록.xlsx 에 파일명과 제목 등을 적으면 됩니다.\n", encoding="utf-8"
        )
    if Path(path).exists():
        print(f"이미 존재: {path} (건드리지 않음)")
        return False

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME

    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    for i, h in enumerate(HEADERS, start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = COLUMN_WIDTHS.get(h, 15)
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"

    # 예시 행 (상태=예시 → 엔진이 건너뜀)
    sample = {
        "파일명": "예시영상.mp4",
        "제목": "예시: 원어민이 매일 쓰는 표현 5가지",
        "캡션": "이 표현 모르면 손해봅니다.",
        "인스타캡션": "(선택) 인스타에만 다르게 쓸 캡션",
        "해시태그": "#쇼츠 #영어회화",
        "플랫폼": "전체",
        "예약시각": "2026-07-15 09:00",
        "공개설정": "공개",
        "상태": "예시",
        "메모": "이 행은 예시입니다. 지우지 말고 참고만 하세요.",
    }
    for i, h in enumerate(HEADERS, start=1):
        ws.cell(row=2, column=i, value=sample.get(h, ""))
        ws.cell(row=2, column=i).font = Font(color="999999", italic=True)

    # 입력 도움 드롭다운 (강제 아님 — 자유 입력도 허용)
    def dropdown(options: str, col_header: str):
        dv = DataValidation(type="list", formula1=f'"{options}"', allow_blank=True,
                            showErrorMessage=False)
        ws.add_data_validation(dv)
        col = get_column_letter(HEADERS.index(col_header) + 1)
        dv.add(f"{col}3:{col}500")

    dropdown("전체,유튜브,인스타,틱톡", "플랫폼")
    dropdown("공개,비공개,일부공개", "공개설정")
    dropdown("대기,보류", "상태")

    # 작성법 시트
    guide = wb.create_sheet("작성법")
    guide.column_dimensions["A"].width = 110
    for r, (text, bold) in enumerate(GUIDE_LINES, start=1):
        c = guide.cell(row=r, column=1, value=text)
        c.font = Font(bold=bold, size=12 if bold else 11)
        c.alignment = Alignment(wrap_text=False)

    wb.save(path)
    print(f"생성 완료: {path}")
    return True


if __name__ == "__main__":
    make()
