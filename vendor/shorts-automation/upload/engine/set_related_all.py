"""이미 업로드된 모든 쇼츠에 관련 동영상을 일괄 설정 (소급 적용).

엑셀의 유튜브결과 열에서 영상 ID를 모아, config의 related_video_id 롱폼으로 연결한다.
성공 이력은 logs/related_journal.json 에 기록해 재실행 시 이미 된 것은 건너뛴다.

사용: python engine/set_related_all.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from settings import EXCEL_PATH, LOGS_DIR, get_logger, load_config  # noqa: E402
from yt_related import YouTubeStudio  # noqa: E402

REL_JOURNAL = LOGS_DIR / "related_journal.json"
YT_ID_RE = re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})")


def load_journal() -> dict:
    if REL_JOURNAL.exists():
        try:
            return json.loads(REL_JOURNAL.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_journal(data: dict) -> None:
    tmp = REL_JOURNAL.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(REL_JOURNAL)


def collect_video_ids() -> list:
    from openpyxl import load_workbook
    wb = load_workbook(EXCEL_PATH)
    ws = wb["업로드목록"]
    hdr = {ws.cell(1, c).value: c for c in range(1, ws.max_column + 1)}
    out = []
    for r in range(2, ws.max_row + 1):
        val = str(ws.cell(r, hdr["유튜브결과"]).value or "")
        m = YT_ID_RE.search(val)
        if m:
            fn = str(ws.cell(r, hdr["파일명"]).value or "")
            out.append((m.group(1), fn))
    return out


def _resolve_title(config: dict, rel_id: str, log) -> str:
    rel_title = config.get("related_video_title", "")
    if rel_title:
        return rel_title
    import requests
    try:
        r = requests.get("https://www.youtube.com/oembed",
                         params={"url": f"https://www.youtube.com/watch?v={rel_id}", "format": "json"},
                         timeout=20)
        rel_title = r.json().get("title", "")
        config["related_video_title"] = rel_title
        from settings import CONFIG_PATH
        CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.error(f"대상 롱폼 제목 조회 실패: {e}")
    return rel_title


def backfill(config: dict, log, quiet_when_empty: bool = False) -> tuple:
    """미설정 영상에 관련 동영상 일괄 적용. (성공, 실패) 반환.

    quiet_when_empty=True 면 처리할 게 없을 때 조용히(로그 최소) 종료 — 엔진 통합용.
    관련 동영상 기능이 꺼져 있거나(related_video_id 없음) 스튜디오 미연결이면 (0,0) 반환.
    """
    rel_id = config.get("related_video_id", "")
    if not rel_id or not config.get("auto_related", True):
        return (0, 0)

    videos = collect_video_ids()
    journal = load_journal()
    todo = [(vid, fn) for vid, fn in videos if journal.get(vid) != rel_id]
    if not todo:
        if not quiet_when_empty:
            log.info("관련 동영상: 모두 이미 설정되어 있습니다.")
        return (0, 0)

    rel_title = _resolve_title(config, rel_id, log)
    if not rel_title:
        return (0, 0)

    studio = YouTubeStudio(rel_id, rel_title)
    if not studio.connected():
        log.warning("관련 동영상: 스튜디오 미연결 — setup/5_유튜브스튜디오_연결.command 실행 후 자동 적용됩니다.")
        return (0, 0)

    log.info(f"관련 동영상 설정: 미처리 {len(todo)}개 → '{rel_title[:20]}'")
    ok, fail = 0, 0
    try:
        for i, (vid, fn) in enumerate(todo, 1):
            log.info(f"[관련동영상 {i}/{len(todo)}] {vid}  {fn[:24]}")
            result = studio.set_related(vid)
            if result.ok:
                journal[vid] = rel_id
                save_journal(journal)
                ok += 1
            else:
                fail += 1
                log.warning(f"  실패: {result.message}")
            time.sleep(2)
    finally:
        studio.close()
    log.info(f"========== 관련 동영상 설정 종료: 성공 {ok} / 실패 {fail} ==========")
    if fail:
        log.info("실패분은 다음 실행 때 남은 것만 자동 재시도됩니다.")
    return (ok, fail)


def main() -> int:
    log = get_logger()
    config = load_config()
    if not config.get("related_video_id"):
        log.error("config.json 에 related_video_id 가 없습니다.")
        return 1
    backfill(config, log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
