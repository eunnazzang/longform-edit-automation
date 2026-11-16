#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""예시(레퍼런스) 영상의 편집 호흡을 수치로 뽑는다.

사용:  ref_analyze.py 편집자료/레퍼런스/예시.mp4 --out 편집자료/레퍼런스/분석/ [--thresh 0.3]
출력:  분석.json  — 컷 시각, 컷 길이 통계(평균·중간값·분당 컷 수), 라우드니스(LUFS/LRA/피크)
       sheet_01.jpg …  — 샷마다 가운데 프레임을 타임코드와 함께 4×5 격자로 (직접 열어서 볼 것)
자막 디자인·로고·줌·전환 방식은 수치로 안 나온다. 시트를 보고 관찰.md에 적는다.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import FFMPEG, probe, run, save_json, ts  # noqa: E402

TILE_W, COLS, ROWS = 384, 4, 5


def detect_cuts(path: str, thresh: float) -> list[float]:
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path, "-an", "-vf",
                        f"scale=320:-2,select='gt(scene,{thresh})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [float(m) for m in re.findall(r"pts_time:([\d.]+)", p.stderr)]


def loudness(path: str) -> dict:
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path, "-vn", "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True)
    tail = p.stderr[p.stderr.rfind("Summary:"):]
    get = lambda k: float(re.search(k + r":\s+(-?[\d.]+)", tail).group(1))  # noqa: E731
    return {"integrated_lufs": get("I"), "lra": get("LRA"), "true_peak_dbfs": get("Peak")}


def contact_sheets(path: str, times: list[float], labels: list[str], out_dir: str, prefix="sheet"):
    from PIL import Image, ImageDraw
    tmp = os.path.join(out_dir, "_frames")
    os.makedirs(tmp, exist_ok=True)
    frames = []
    for i, t in enumerate(times):
        f = os.path.join(tmp, f"{i:04d}.jpg")
        run([FFMPEG, "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
             "-vf", f"scale={TILE_W}:-2", "-q:v", "4", f])
        frames.append(f)
    per = COLS * ROWS
    sheets = []
    for s in range(0, len(frames), per):
        imgs = [Image.open(f) for f in frames[s:s + per]]
        h = imgs[0].height
        sheet = Image.new("RGB", (COLS * TILE_W, ROWS * (h + 22)), "black")
        d = ImageDraw.Draw(sheet)
        for j, im in enumerate(imgs):
            x, y = (j % COLS) * TILE_W, (j // COLS) * (h + 22)
            sheet.paste(im, (x, y))
            d.text((x + 4, y + h + 4), labels[s + j], fill="white")
        name = os.path.join(out_dir, f"{prefix}_{s // per + 1:02d}.jpg")
        sheet.save(name, quality=85)
        sheets.append(name)
    for f in frames:
        os.remove(f)
    os.rmdir(tmp)
    return sheets


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--out", required=True)
    ap.add_argument("--thresh", type=float, default=0.3, help="장면 전환 감도(낮을수록 많이 잡음)")
    ap.add_argument("--max-frames", type=int, default=80)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    info = probe(a.video)
    dur = info["duration"]
    print("컷 감지 중…")
    cuts = detect_cuts(a.video, a.thresh)
    bounds = [0.0] + cuts + [dur]
    shots = np.diff(bounds)
    stats = {
        "duration": round(dur, 2), "cuts": len(cuts),
        "cuts_per_min": round(len(cuts) / (dur / 60), 2),
        "shot_mean": round(float(shots.mean()), 2), "shot_median": round(float(np.median(shots)), 2),
        "shot_p10": round(float(np.percentile(shots, 10)), 2),
        "shot_p90": round(float(np.percentile(shots, 90)), 2),
        "intro_first_cut": round(cuts[0], 2) if cuts else None,
    }
    # 1분 단위 컷 수 — 인트로가 더 빠른지, 후반에 늘어지는지
    stats["cuts_by_minute"] = [int(((np.array(cuts) >= m * 60) & (np.array(cuts) < (m + 1) * 60)).sum())
                               for m in range(int(np.ceil(dur / 60)))]
    print("라우드니스 측정 중…")
    stats["loudness"] = loudness(a.video)
    stats["video"] = info

    mids = [(bounds[i] + bounds[i + 1]) / 2 for i in range(len(shots))]
    if len(mids) > a.max_frames:
        idx = np.linspace(0, len(mids) - 1, a.max_frames).astype(int)
        mids = [mids[i] for i in idx]
    labels = [ts(t) for t in mids]
    stats["sheets"] = contact_sheets(a.video, mids, labels, a.out)
    stats["cut_times"] = [round(c, 2) for c in cuts]
    save_json(stats, os.path.join(a.out, "분석.json"))
    print(f"컷 {len(cuts)}개, 분당 {stats['cuts_per_min']}, 평균 샷 {stats['shot_mean']}s, "
          f"{stats['loudness']['integrated_lufs']} LUFS")
    print(f"→ {a.out}/분석.json, 시트 {len(stats['sheets'])}장")


if __name__ == "__main__":
    main()
