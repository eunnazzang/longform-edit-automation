#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""카메라별 색·밝기를 기준 카메라에 맞춘다(채널별 평균·표준편차 매칭).

사용:  color_match.py 편집자료/편집결정.json --ref A [--out 편집자료/색보정.json] [--dry]
동작:  편집결정의 컷들에서 카메라마다 프레임을 뽑아 RGB 채널별 평균·표준편차를 재고,
       기준 카메라와 같아지는 선형 보정(gain, offset)을 sources.<캠>.grade.rgb 에 써 넣는다.
       기준 캠 자신도 예시 톤에 맞추고 싶으면 grade.eq 에 "brightness=0.02:saturation=1.08" 같이 손으로 더한다.
보정 뒤 qc.py의 컷별 밝기 편차와 이음새 시트로 결과를 확인한다.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import FFMPEG, load_json, probe, resolve, save_json  # noqa: E402

W = 320


def grab(path: str, t: float, h: int) -> np.ndarray:
    raw = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", path, "-frames:v", "1",
                          "-vf", f"scale={W}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, W, 3).astype(np.float32)


def stats(edl_path: str, edl: dict, cam: str, n: int = 12) -> np.ndarray:
    src = edl["sources"][cam]
    path = resolve(edl_path, src["video"])
    info = probe(path)
    h = int(round(W * info["height"] / info["width"] / 2) * 2)
    cuts = [c for c in edl["cuts"] if c["cam"] == cam]
    if not cuts:
        return None
    pick = [cuts[i] for i in np.linspace(0, len(cuts) - 1, min(n, len(cuts))).astype(int)]
    times = [(c["in"] + c["out"]) / 2 - src.get("video_offset", 0) for c in pick]
    bad = [t for t in times if not 0 <= t < info["duration"]]
    if bad:
        raise SystemExit(f"{cam}: 카메라 녹화 범위(0~{info['duration']:.1f}s) 밖 컷이 있다 — cam_t {bad}")
    px = np.concatenate([grab(path, t, h).reshape(-1, 3) for t in times])
    return np.stack([px.mean(0), px.std(0)])  # [[mR,mG,mB],[sR,sG,sB]]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("edl")
    ap.add_argument("--ref", required=True, help="기준 카메라 이름")
    ap.add_argument("--out", default=None)
    ap.add_argument("--dry", action="store_true", help="편집결정을 고치지 않고 보고만")
    a = ap.parse_args()

    edl = load_json(a.edl)
    st = {cam: stats(a.edl, edl, cam) for cam in edl["sources"]}
    ref = st[a.ref]
    report = {}
    for cam, s in st.items():
        if s is None:
            continue
        g = edl["sources"][cam].setdefault("grade", {})
        if cam == a.ref:
            g.pop("rgb", None)
            report[cam] = {"ref": True, "mean": s[0].round(1).tolist()}
            continue
        gain = np.clip(ref[1] / (s[1] + 1e-6), 0.7, 1.4)
        off = ref[0] - gain * s[0]
        g["rgb"] = [[round(float(gain[i]), 4), round(float(off[i]), 2)] for i in range(3)]
        report[cam] = {"mean_before": s[0].round(1).tolist(), "mean_target": ref[0].round(1).tolist(),
                       "gain_offset": g["rgb"]}
        print(f"{cam}: 평균 RGB {s[0].round(0).tolist()} → {ref[0].round(0).tolist()}  gain {gain.round(3).tolist()}")
    if a.out:
        save_json(report, a.out)
    if not a.dry:
        shutil.copy(a.edl, a.edl + ".bak")
        save_json(edl, a.edl)
        print(f"편집결정에 반영 (이전본 {os.path.basename(a.edl)}.bak)")


if __name__ == "__main__":
    main()
