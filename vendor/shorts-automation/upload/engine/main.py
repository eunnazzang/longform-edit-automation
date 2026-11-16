"""자동 업로드 엔진 — 실행 진입점.

동작:
1. 감시 폴더의 새 영상을 엑셀에 '검토대기'로 자동 등록 (업로드는 안 함)
2. 예약시각이 지난 '대기' 행 → 유튜브·인스타에 즉시 업로드
3. 예약시각이 미래인 '대기' 행 → 유튜브만 미리 올려두고 서버 예약(publishAt)
   (유튜브가 그 시각에 알아서 공개하므로 Mac이 꺼져 있어도 됨.
    인스타는 예약 API가 없어 해당 시각 이후 첫 실행 때 게시)
4. 결과를 엑셀에 기록, 모든 플랫폼 완료 시 영상을 업로드완료/로 이동

중복 방지: 성공 이력은 파일 내용 지문 기준 장부(logs/journal.json)에 기록.
같은 영상은 파일명이 바뀌어도 다시 올라가지 않는다.

사용: python engine/main.py [--dry-run]
"""
from __future__ import annotations

import fcntl
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from settings import (  # noqa: E402
    CONFIG_DIR, EXCEL_PATH, RESULT_COLUMNS,
    ensure_dirs, file_fingerprint, get_done_dir, get_logger, get_pending_dir,
    load_config, now_str,
)
from excel_manager import ExcelManager, SKIP_STATUS  # noqa: E402
from journal import Journal  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".m4v"}


def acquire_lock():
    """동시 실행 방지 (자동실행과 수동실행이 겹쳐도 안전)."""
    lock_file = open(CONFIG_DIR / ".run.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except OSError:
        return None


def file_ready(path: Path) -> bool:
    """복사가 끝난 파일인지 확인 (2초 간격 크기 비교)."""
    s1 = path.stat().st_size
    time.sleep(2)
    return path.stat().st_size == s1 and s1 > 0


def find_video(pending_dir: Path, filename: str) -> Path | None:
    p = pending_dir / filename
    if p.exists():
        return p
    if "." not in filename:
        for ext in (".mp4", ".mov", ".MP4", ".MOV", ".m4v"):
            q = pending_dir / (filename + ext)
            if q.exists():
                return q
    return None


def move_to_done(done_dir: Path, path: Path) -> Path:
    done_dir.mkdir(parents=True, exist_ok=True)
    target = done_dir / path.name
    if target.exists():
        target = done_dir / f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}"
    shutil.move(str(path), str(target))
    return target


def auto_ingest(excel: ExcelManager, pending_dir: Path, log) -> int:
    """폴더에 새로 들어온 영상을 '검토대기' 행으로 자동 추가 (업로드는 하지 않음)."""
    if not pending_dir.exists():
        return 0
    known = excel.known_filenames()
    added = 0
    for f in sorted(pending_dir.iterdir()):
        if f.suffix.lower() not in VIDEO_EXTS or f.name.startswith("."):
            continue
        if f.name in known:
            continue
        excel.append_new_video(f.name)
        log.info(f"새 영상 자동 감지: {f.name} → '검토대기'로 목록에 추가")
        added += 1
    if added:
        excel.save()
        log.info(f"새 영상 {added}개는 캡션 확인 후 상태를 '대기'로 바꾸면 업로드됩니다.")
    return added


def main(argv: list) -> int:
    dry_run = "--dry-run" in argv
    log = get_logger()
    ensure_dirs()
    config = load_config()

    if not EXCEL_PATH.exists():
        log.error("업로드목록.xlsx 가 없습니다. setup/1_초기설정.command 를 먼저 실행하세요.")
        return 1

    lock = acquire_lock()
    if lock is None:
        log.info("이미 다른 업로드가 실행 중입니다. 이번 회차는 건너뜁니다.")
        return 0

    log.info("========== 자동 업로드 실행 ==========")
    try:
        excel = ExcelManager(EXCEL_PATH, config)
        excel.preflight_save()
    except Exception as e:
        log.error(str(e))
        return 1

    journal = Journal()
    now = datetime.now()
    pending_dir = get_pending_dir(config)
    done_dir = get_done_dir(config)
    auto_ingest(excel, pending_dir, log)

    # 처리 대상 분류: 정시(due) / 유튜브 사전예약(early)
    due, early = [], []
    for row in excel.iter_rows():
        if row.status in SKIP_STATUS:
            continue
        if row.error:
            if row.status != "입력 오류":
                excel.set(row.index, "상태", "입력 오류")
                for pf in row.platforms or list(RESULT_COLUMNS):
                    excel.set(row.index, RESULT_COLUMNS[pf], f"실패: {row.error}")
                excel.save()
            log.warning(f"{row.index}행 {row.filename}: {row.error}")
            continue
        if row.schedule and row.schedule > now:
            if ("유튜브" in row.platforms
                    and row.visibility in ("공개", "비공개")
                    and not row.results.get("유튜브", "").startswith("완료")):
                early.append(row)
            continue
        due.append(row)

    if not due and not early:
        log.info("처리할 항목이 없습니다.")
        return 0

    log.info(f"처리 대상: 정시 업로드 {len(due)}건 / 유튜브 사전예약 {len(early)}건")
    if dry_run:
        for row in due:
            log.info(f"  [예행·정시] {row.index}행 {row.filename} → {','.join(row.platforms)}")
        for row in early:
            log.info(f"  [예행·사전예약] {row.index}행 {row.filename} → 유튜브 (공개 {row.schedule:%m/%d %H:%M})")
        log.info("--dry-run 이므로 실제 업로드는 하지 않았습니다.")
        return 0

    from yt_uploader import YouTubeUploader, UploadResult
    yt = YouTubeUploader()
    ig = None
    tunnel = None
    ok_count, fail_count, prescheduled = 0, 0, 0
    quota_stop = False

    tt = None

    def upload_one(row, pf: str, path: Path, publish_at):
        nonlocal ig, tunnel, tt
        try:
            if pf == "유튜브":
                return yt.upload(row, path, publish_at=publish_at)
            if pf == "틱톡":
                if tt is None:
                    from tt_api_uploader import TikTokApiUploader
                    tt = TikTokApiUploader(config)
                return tt.upload(row, path)
            if ig is None:
                from ig_uploader import InstagramUploader
                from tunnel import FileTunnel
                ig = InstagramUploader(config)
                tunnel = FileTunnel()
            return ig.upload(row, path, tunnel)
        except Exception as e:
            return UploadResult(False, f"예상치 못한 오류: {e}")

    def run_platforms(row, path: Path, platforms: list, publish_at) -> bool:
        """지정 플랫폼 업로드. 반환값: 유튜브 할당량 소진 여부."""
        quota_hit = False
        fp = file_fingerprint(path)
        for pf in platforms:
            past = journal.done(fp, pf)
            if past:
                excel.set(row.index, RESULT_COLUMNS[pf], f"완료 {past['url']}".strip())
                excel.save()
                continue
            if str(excel._get(row.index, RESULT_COLUMNS[pf]) or "").startswith("완료"):
                continue
            result = upload_one(row, pf, path, publish_at if pf == "유튜브" else None)
            if result.ok:
                journal.record(fp, pf, result.url, path.name)
                excel.set(row.index, RESULT_COLUMNS[pf], f"{result.message} {result.url}".strip())
                log.info(f"  {pf}: {result.message} {result.url}")
            else:
                excel.set(row.index, RESULT_COLUMNS[pf], f"실패({now_str()}): {result.message}")
                log.warning(f"  {pf}: 실패 — {result.message}")
                if pf == "유튜브" and "할당량" in result.message:
                    quota_hit = True
            excel.save()
        return quota_hit

    def succeeded_platforms(row) -> list:
        return [
            pf for pf in row.platforms
            if str(excel._get(row.index, RESULT_COLUMNS[pf]) or "").startswith("완료")
        ]

    try:
        # ---------- 1) 정시 업로드 ----------
        for row in due:
            path = find_video(pending_dir, row.filename)
            if path is None:
                msg = f"실패: 폴더에 '{row.filename}' 파일이 없습니다."
                excel.set(row.index, "상태", "실패")
                for pf in row.platforms:
                    if not row.results.get(pf, "").startswith("완료"):
                        excel.set(row.index, RESULT_COLUMNS[pf], msg)
                excel.save()
                log.warning(f"{row.index}행: {msg}")
                fail_count += 1
                continue
            if not file_ready(path):
                log.info(f"{row.index}행 {path.name}: 파일 복사 중으로 보여 이번 회차는 건너뜁니다.")
                continue

            log.info(f"--- {row.index}행 정시 업로드: {path.name} → {','.join(row.platforms)}")
            excel.set(row.index, "상태", "처리중")
            excel.save()
            if run_platforms(row, path, row.platforms, publish_at=None):
                quota_stop = True

            done = succeeded_platforms(row)
            if len(done) == len(row.platforms):
                excel.set(row.index, "상태", "완료")
                excel.set(row.index, "업로드시각", now_str())
                moved = move_to_done(done_dir, path)
                log.info(f"  모든 플랫폼 완료 → 파일 이동: 업로드완료/{moved.name}")
                ok_count += 1
            else:
                excel.set(row.index, "상태", "일부실패" if done else "실패")
                fail_count += 1
            excel.save()

        # ---------- 2) 유튜브 사전예약 (미래 행을 미리 올려 서버 예약) ----------
        for row in early:
            if quota_stop:
                log.info("유튜브 API 일일 할당량 소진 — 남은 사전예약은 다음 실행(내일)에 자동 진행됩니다.")
                break
            path = find_video(pending_dir, row.filename)
            if path is None:
                log.warning(f"{row.index}행 {row.filename}: 폴더에 파일이 없어 사전예약을 건너뜁니다.")
                continue
            if not file_ready(path):
                continue

            log.info(f"--- {row.index}행 유튜브 사전예약: {path.name} (공개 {row.schedule:%m/%d %H:%M})")
            excel.set(row.index, "상태", "처리중")
            excel.save()
            if run_platforms(row, path, ["유튜브"], publish_at=row.schedule):
                quota_stop = True

            done = succeeded_platforms(row)
            if len(done) == len(row.platforms):
                # 유튜브만 대상인 행은 사전예약으로 행 자체가 완료됨
                excel.set(row.index, "상태", "완료")
                excel.set(row.index, "업로드시각", now_str())
                moved = move_to_done(done_dir, path)
                log.info(f"  모든 플랫폼 완료 → 파일 이동: 업로드완료/{moved.name}")
                ok_count += 1
            else:
                # 인스타는 예약시각에 올라가야 하므로 다시 '대기'로
                excel.set(row.index, "상태", "대기")
                if str(excel._get(row.index, RESULT_COLUMNS["유튜브"]) or "").startswith("완료"):
                    prescheduled += 1
            excel.save()
    finally:
        if tunnel is not None:
            tunnel.stop()
        try:
            excel.save()
        except Exception:
            pass

    log.info(
        f"========== 실행 종료: 완료 {ok_count}건 / 유튜브 사전예약 {prescheduled}건 / 실패 {fail_count}건 =========="
    )
    if fail_count:
        log.info("실패한 행은 사유를 고친 뒤 그대로 두면 다음 실행 때 자동으로 재시도됩니다.")

    # 새로 올라온(또는 아직 미설정된) 쇼츠에 관련 동영상 자동 설정
    try:
        from set_related_all import backfill
        backfill(config, log, quiet_when_empty=True)
    except Exception as e:
        log.warning(f"관련 동영상 자동 설정 단계 건너뜀: {e}")

    # 업로드된 영상 중 아직 제품 태그가 안 된 것에 자동 적용
    try:
        from tag_products_all import backfill_new
        backfill_new(config, log)
    except Exception as e:
        log.warning(f"제품 태그 단계 건너뜀: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
