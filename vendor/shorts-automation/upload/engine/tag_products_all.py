"""채널의 모든 영상(롱폼+쇼츠)에 config의 제품 4개를 일괄 태그 (소급 적용).

스튜디오 콘텐츠 목록에서 영상 ID를 수집한 뒤 하나씩 제품을 태그한다.
성공 이력은 logs/product_journal.json 에 남겨 재실행 시 이미 된 것은 건너뛴다.
중간에 멈춰도 다시 실행하면 남은 것부터 이어서 진행한다.

사용:
  python engine/tag_products_all.py              # 전체(이미 태그된 영상은 건너뜀)
  python engine/tag_products_all.py --retag      # 기존 태그를 지우고 다시 태그
  python engine/tag_products_all.py --limit 10   # 앞에서 N편만
  python engine/tag_products_all.py --ids a,b,c  # 특정 영상만
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from settings import CONFIG_DIR, LOGS_DIR, get_logger, load_config  # noqa: E402
from yt_products import ProductTagger, PROFILE_DIR  # noqa: E402

JOURNAL = LOGS_DIR / "product_journal.json"
VIDEO_CACHE = LOGS_DIR / "channel_videos.json"

_ROWS_JS = """()=>{
  const out=[]; const seen=new Set();
  const walk=(r)=>{
    for(const a of (r.querySelectorAll?r.querySelectorAll('a[href*="/video/"]'):[])){
      const m=(a.getAttribute('href')||'').match(/\\/video\\/([A-Za-z0-9_-]{11})\\//);
      if(m && !seen.has(m[1])){ seen.add(m[1]);
        const row=a.closest('ytcp-video-row'); let title='';
        if(row){ const el=row.querySelector('#video-title'); title=(el?el.innerText:'').trim(); }
        out.push({id:m[1], title:title.slice(0,60)}); }
    }
    for(const e of (r.querySelectorAll?r.querySelectorAll('*'):[])) if(e.shadowRoot) walk(e.shadowRoot);
  };
  walk(document); return out;
}"""
_NEXT_JS = """()=>{ const f=(r)=>{
  for(const e of (r.querySelectorAll?r.querySelectorAll('ytcp-icon-button,button'):[])){
    const a=(e.getAttribute('aria-label')||'');
    if(a.includes('다음 페이지')||a.toLowerCase().includes('next page')) return e; }
  for(const e of (r.querySelectorAll?r.querySelectorAll('*'):[])) if(e.shadowRoot){const x=f(e.shadowRoot); if(x)return x;}
  return null;}; const el=f(document);
  if(!el) return 'nobutton';
  if(el.hasAttribute('disabled')||el.getAttribute('aria-disabled')==='true') return 'disabled';
  el.click(); return 'ok';}"""


def load_journal() -> dict:
    if JOURNAL.exists():
        try:
            return json.loads(JOURNAL.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_journal(d: dict) -> None:
    tmp = JOURNAL.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(JOURNAL)


def collect_videos(tagger: ProductTagger, log, refresh: bool = False) -> list:
    """스튜디오 콘텐츠 목록에서 전체 영상 수집(캐시 사용)."""
    if VIDEO_CACHE.exists() and not refresh:
        try:
            data = json.loads(VIDEO_CACHE.read_text(encoding="utf-8"))
            if data:
                log.info(f"영상 목록 캐시 사용: {len(data)}편 (갱신하려면 --refresh)")
                return data
        except Exception:
            pass
    tagger._launch()
    page = tagger.page
    page.goto("https://studio.youtube.com/", wait_until="domcontentloaded", timeout=60_000)
    time.sleep(8)
    m = re.search(r"/channel/(UC[\w-]+)", page.url)
    if not m:
        log.error("채널 ID를 찾지 못했습니다(로그인 확인).")
        return []
    cid = m.group(1)
    allv: dict = {}
    for tab, label in [("videos/upload", "롱폼"), ("videos/short", "쇼츠")]:
        page.goto(f"https://studio.youtube.com/channel/{cid}/{tab}", wait_until="domcontentloaded", timeout=60_000)
        time.sleep(9)
        for _ in range(40):
            for _ in range(6):
                page.mouse.wheel(0, 3000)
                time.sleep(1.0)
            for r in page.evaluate(_ROWS_JS):
                allv.setdefault(r["id"], {**r, "kind": label})
            if page.evaluate(_NEXT_JS) != "ok":
                break
            time.sleep(6)
        log.info(f"  {label} 수집 누적: {len(allv)}편")
    data = list(allv.values())
    VIDEO_CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


YT_ID_RE = re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})")


def excel_video_ids() -> list:
    """엑셀 유튜브결과 열에서 업로드된 영상 ID 수집."""
    from openpyxl import load_workbook
    from settings import EXCEL_PATH
    wb = load_workbook(EXCEL_PATH)
    ws = wb["업로드목록"]
    hdr = {ws.cell(1, c).value: c for c in range(1, ws.max_column + 1)}
    out = []
    for r in range(2, ws.max_row + 1):
        m = YT_ID_RE.search(str(ws.cell(r, hdr["유튜브결과"]).value or ""))
        if m:
            out.append(m.group(1))
    return out


def backfill_new(config: dict, log, video_ids: list | None = None) -> None:
    """업로드 직후 호출 — 아직 태그 안 된 업로드분에만 제품 태그."""
    products = config.get("products") or []
    if not products:
        return
    if video_ids is None:
        try:
            video_ids = excel_video_ids()
        except Exception as e:
            log.warning(f"제품 태그: 영상 ID 수집 실패 — {e}")
            return
    if not video_ids:
        return
    journal = load_journal()
    todo = [v for v in video_ids if v not in journal]
    if not todo:
        return
    if not PROFILE_DIR.exists():
        log.warning("제품 태그 건너뜀 — 스튜디오 미연결")
        return
    log.info(f"제품 태그: 신규 {len(todo)}편 처리")
    tagger = ProductTagger(products)
    try:
        for vid in todo:
            try:
                r = tagger.tag(vid)
            except Exception as e:
                log.warning(f"  제품 태그 실패 {vid}: {e}")
                continue
            if r.ok:
                journal[vid] = {"title": "", "msg": r.message, "kind": "신규"}
                save_journal(journal)
            else:
                log.warning(f"  제품 태그 실패 {vid}: {r.message}")
            time.sleep(2)
    finally:
        tagger.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retag", action="store_true", help="기존 태그를 지우고 다시 태그")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="")
    ap.add_argument("--refresh", action="store_true", help="영상 목록 새로 수집")
    args = ap.parse_args()

    log = get_logger()
    cfg = load_config()
    products = cfg.get("products") or []
    if not products:
        log.error("config.json 에 products 가 없습니다.")
        return 1
    if not PROFILE_DIR.exists():
        log.error("스튜디오 미연결 — setup/5_유튜브스튜디오_연결.command 실행 필요.")
        return 1

    log.info("=" * 60)
    log.info(f"제품 태그 일괄 적용 시작 (제품 {len(products)}개)")
    for p in products:
        log.info(f"  · {p['exact'][:40]} ({p.get('seller','')} {p.get('price','')})")

    tagger = ProductTagger(products)
    journal = load_journal()
    try:
        if args.ids:
            targets = [{"id": i.strip(), "title": "", "kind": "지정"} for i in args.ids.split(",") if i.strip()]
        else:
            targets = collect_videos(tagger, log, refresh=args.refresh)
        if args.limit:
            targets = targets[: args.limit]

        todo = [v for v in targets if args.retag or v["id"] not in journal]
        log.info(f"대상 {len(targets)}편 중 처리 필요 {len(todo)}편 (완료 이력 {len(journal)}건)")

        done = fail = skip = 0
        for i, v in enumerate(todo, 1):
            vid, title = v["id"], (v.get("title") or "")[:32]
            log.info(f"[{i}/{len(todo)}] {vid} {title}")
            try:
                r = tagger.tag(vid, retag=args.retag)
            except Exception as e:  # 개별 실패가 전체를 멈추지 않게
                r = type("R", (), {"ok": False, "message": f"예외: {e}"})()
            if r.ok and "부분태그" in r.message:
                fail += 1
                log.warning(f"   부분 태그 — 재시도 대상으로 남김: {r.message}")
            elif r.ok:
                if "이미태그됨" in r.message:
                    skip += 1
                else:
                    done += 1
                journal[vid] = {"title": title, "msg": r.message, "kind": v.get("kind", "")}
                save_journal(journal)
            else:
                fail += 1
                log.warning(f"   실패: {r.message}")
            time.sleep(2)
        log.info("=" * 60)
        log.info(f"제품 태그 종료: 신규 {done} / 이미됨 {skip} / 실패 {fail}")
        log.info("실패분은 다시 실행하면 남은 것만 자동 재시도됩니다.")
    finally:
        tagger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
