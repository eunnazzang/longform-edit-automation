#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SD카드(카메라·녹음기 메모리)를 프로젝트 촬영본 폴더로 백업하고 체크섬으로 검증한다.

사용:
  sd_backup.py --list                                   # 꽂혀 있는 카드와 추정 카메라만 보여 준다
  sd_backup.py --project <프로젝트 폴더> --card /Volumes/<카드> --label A캠 [--dry-run]
  sd_backup.py --project <프로젝트 폴더> --all           # 감지된 카드 전부, 라벨은 추정값

결과:
  <프로젝트>/촬영본/<라벨>/<촬영일>_<카드이름>/...   (카드 안 폴더 구조 그대로)
  <프로젝트>/편집자료/백업로그/<촬영일>_<라벨>_<카드이름>.json   (파일별 크기·MD5·검증 결과)

규칙: 카드에는 절대 쓰거나 지우지 않는다. 복사하면서 원본 MD5를 계산하고, 복사본을 다시 읽어
      MD5를 대조한다. 이미 같은 크기·같은 MD5로 백업된 파일은 건너뛴다(중단 후 이어하기 가능).
      검증 실패가 하나라도 있으면 종료 코드 1 — 그때는 카드를 포맷하지 말라고 사용자에게 알린다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from common import SHOOT, WORK, load_json, nfc, save_json  # noqa: E402

MEDIA = {".mp4", ".mov", ".mxf", ".mts", ".m2ts", ".avi", ".braw", ".r3d", ".crm", ".insv", ".lrv",
         ".wav", ".mp3", ".m4a", ".bwf", ".jpg", ".jpeg", ".dng", ".arw", ".cr3", ".heic", ".xml", ".thm"}
VIDEO_AUDIO = {".mp4", ".mov", ".mxf", ".mts", ".m2ts", ".avi", ".braw", ".r3d", ".crm", ".insv", ".wav", ".bwf"}
SKIP = {".Spotlight-V100", ".Trashes", ".fseventsd", ".TemporaryItems", "System Volume Information"}
CHUNK = 8 * 1024 * 1024


def is_removable(mount: str) -> bool:
    try:
        out = subprocess.run(["diskutil", "info", "-plist", mount], capture_output=True, check=True).stdout
        info = plistlib.loads(out)
        if info.get("Internal") is True and not info.get("RemovableMedia"):
            return False
        return True
    except Exception:
        return True  # diskutil이 없으면(리눅스 테스트 등) 미디어 유무로만 판단


def walk_media(root: str, max_depth: int = 6):
    root_depth = root.rstrip("/").count("/")
    for d, ds, fs in os.walk(root):
        ds[:] = [x for x in ds if x not in SKIP and not x.startswith(".")]
        if d.count("/") - root_depth >= max_depth:
            ds[:] = []
        for f in fs:
            if f.startswith("."):
                continue
            yield os.path.join(d, f)


def guess_camera(mount: str) -> str:
    names = set()
    for d, ds, fs in os.walk(mount):
        ds[:] = [x for x in ds if not x.startswith(".")]
        names.update(x.upper() for x in ds + fs)
        if d.count("/") - mount.count("/") > 2:
            ds[:] = []
    j = " ".join(names)
    if "M4ROOT" in names or "XDROOT" in names:
        return "소니"
    if "DJI" in j:
        return "DJI"
    if "GOPRO" in j:
        return "고프로"
    if "CANON" in j or "CONTENTS" in names:
        return "캐논"
    if "ZOOM" in j or any(n.endswith(".WAV") for n in names):
        return "사운드"
    if "INSV" in j or "INSTA360" in j:
        return "인스타360"
    if "BRAW" in j:
        return "블랙매직"
    return "카메라"


def list_cards(volumes: str = "/Volumes") -> list[dict]:
    cards = []
    if not os.path.isdir(volumes):
        return cards
    for v in sorted(os.listdir(volumes)):
        m = os.path.join(volumes, v)
        if v.startswith(".") or os.path.islink(m) or v in ("Macintosh HD", "Recovery", "Preboot", "VM", "Data"):
            continue
        if not os.path.isdir(m) or not is_removable(m):
            continue
        files = [p for p in walk_media(m) if os.path.splitext(p)[1].lower() in MEDIA]
        av = [p for p in files if os.path.splitext(p)[1].lower() in VIDEO_AUDIO]
        if not av:
            continue
        size = sum(os.path.getsize(p) for p in files)
        first = min(os.path.getmtime(p) for p in av)
        cards.append({"mount": m, "name": nfc(v), "camera": guess_camera(m), "files": len(files),
                      "video_audio": len(av), "gb": round(size / 1e9, 2),
                      "date": dt.datetime.fromtimestamp(first).strftime("%Y%m%d")})
    return cards


def md5_copy(src: str, dst: str) -> str:
    h = hashlib.md5()
    tmp = dst + ".part"
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        while True:
            b = fi.read(CHUNK)
            if not b:
                break
            h.update(b)
            fo.write(b)
    shutil.copystat(src, tmp)
    os.replace(tmp, dst)
    return h.hexdigest()


def md5_file(p: str) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def backup(card: dict, project: str, label: str, dry: bool) -> bool:
    dest = os.path.join(project, SHOOT, label, f"{card['date']}_{card['name']}")
    logp = os.path.join(project, WORK, "백업로그", f"{card['date']}_{label}_{card['name']}.json")
    prev = {r["rel"]: r for r in load_json(logp)["files"]} if os.path.exists(logp) else {}
    files = [p for p in walk_media(card["mount"], 12)]
    total = sum(os.path.getsize(p) for p in files)
    free = shutil.disk_usage(project).free
    print(f"[{label}] {card['mount']} → {dest}\n  파일 {len(files)}개, {total / 1e9:.2f}GB (남은 공간 {free / 1e9:.1f}GB)")
    if total > free:
        print("  ✗ 저장 공간이 부족해요. 백업하지 않았어요.")
        return False
    if dry:
        return True
    rows, ok, done, t0 = [], True, 0, time.time()
    for p in files:
        rel = os.path.relpath(p, card["mount"])
        q = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(q), exist_ok=True)
        size = os.path.getsize(p)
        old = prev.get(rel)
        if old and old.get("verified") and os.path.exists(q) and os.path.getsize(q) == size:
            rows.append(old)
            done += size
            continue
        src_md5 = md5_copy(p, q)
        dst_md5 = md5_file(q)
        good = src_md5 == dst_md5 and os.path.getsize(q) == size
        ok &= good
        rows.append({"rel": rel, "bytes": size, "md5": src_md5, "verified": good})
        done += size
        el = time.time() - t0
        print(f"  {'✓' if good else '✗ 검증 실패'} {rel}  ({done / 1e9:.1f}/{total / 1e9:.1f}GB, "
              f"{done / 1e6 / max(el, 0.1):.0f}MB/s)", flush=True)
        save_json({"card": card, "label": label, "dest": dest, "files": rows}, logp)
    save_json({"card": card, "label": label, "dest": dest, "finished": dt.datetime.now().isoformat(timespec="seconds"),
               "all_verified": ok, "files": rows}, logp)
    print(f"  {'모든 파일 검증 완료' if ok else '⚠ 검증 실패 파일 있음 — 카드 포맷 금지'} · 로그 {logp}")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--project")
    ap.add_argument("--card", action="append", default=[], help="/Volumes/<카드> (여러 번 가능)")
    ap.add_argument("--label", action="append", default=[], help="--card 순서대로 라벨(A캠, B캠, 사운드 …)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--volumes", default="/Volumes", help=argparse.SUPPRESS)
    a = ap.parse_args()

    cards = list_cards(a.volumes)
    if a.list or not a.project:
        if not cards:
            print("감지된 카드가 없어요. 카드를 꽂고 Finder에 보이는지 확인하세요.")
        for c in cards:
            print(f"{c['mount']}\t추정: {c['camera']}\t촬영일 {c['date']}\t영상·음성 {c['video_audio']}개\t{c['gb']}GB")
        return
    chosen = []
    if a.all:
        counter = {}
        for c in cards:
            n = counter[c["camera"]] = counter.get(c["camera"], 0) + 1
            chosen.append((c, c["camera"] if n == 1 else f"{c['camera']}{n}"))
    for i, m in enumerate(a.card):
        c = next((x for x in cards if os.path.realpath(x["mount"]) == os.path.realpath(m)), None)
        if not c:
            sys.exit(f"{m} 에서 영상·음성 파일을 찾지 못했어요.")
        chosen.append((c, a.label[i] if i < len(a.label) else c["camera"]))
    if not chosen:
        sys.exit("--card 또는 --all 을 주세요 (--list 로 먼저 확인).")
    results = [backup(c, a.project, label, a.dry_run) for c, label in chosen]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
