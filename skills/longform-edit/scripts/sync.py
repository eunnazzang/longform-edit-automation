#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""카메라 영상을 외부 사운드(마스터)에 싱크한다 — 오디오 상호상관.

사용:
  sync.py --master 촬영본/사운드/<파일> --cam A=촬영본/A캠/<파일> [--cam B=촬영본/B캠/<파일>] --out 편집자료/싱크.json
출력:
  {"master": ..., "cams": {"A": {"video": ..., "video_offset": 12.345, "confidence": 9.1, "drift_ms": 3}}}
  video_offset = 마스터 타임에서 그 카메라 0초가 놓이는 위치. cam_t = master_t - video_offset
  confidence = 상관 피크 / 주변 표준편차 (4 미만이면 수동 확인)
  drift_ms   = 카메라 앞부분과 뒷부분에서 따로 잰 오프셋 차이
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
from scipy.signal import correlate

sys.path.insert(0, __import__("os").path.dirname(__file__))
from common import load_audio, probe, save_json  # noqa: E402

SR = 8000
WIN = 120.0  # 카메라에서 잘라 비교할 길이(초)


def envelope(x: np.ndarray) -> np.ndarray:
    # 마이크 특성 차이를 줄이려고 원파형 대신 정규화한 파형을 쓴다
    x = x - x.mean()
    return x / (np.std(x) + 1e-9)


def find_offset(master: np.ndarray, cam: np.ndarray) -> tuple[float, float]:
    """cam 조각이 master의 몇 초 지점에 해당하는지."""
    c = correlate(envelope(master), envelope(cam), mode="valid", method="fft")
    k = int(np.argmax(c))
    lo, hi = max(0, k - SR), min(len(c), k + SR)
    around = np.concatenate([c[:lo], c[hi:]]) if len(c) > 2 * SR else c
    conf = float(c[k] / (np.std(around) + 1e-9))
    return k / SR, conf


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--master", required=True)
    ap.add_argument("--cam", action="append", required=True, help="이름=경로")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    mdur = probe(a.master)["duration"]
    print(f"마스터 {a.master} ({mdur:.1f}s) 읽는 중…")
    master = load_audio(a.master, SR)
    res = {"master": a.master, "master_duration": mdur, "cams": {}}
    for spec in a.cam:
        name, path = spec.split("=", 1)
        cdur = probe(path)["duration"]
        if path == a.master:
            res["cams"][name] = {"video": path, "video_offset": 0.0, "confidence": 99.0, "drift_ms": 0}
            continue
        win = min(WIN, cdur * 0.4)
        # 앞쪽 조각(시작 5% 지점)과 뒤쪽 조각(끝 직전)을 각각 맞춰 드리프트를 본다
        s1 = min(cdur * 0.05, max(cdur - win, 0))
        s2 = max(cdur - win - cdur * 0.05, s1)
        offs = []
        for s in (s1, s2):
            pos, conf = find_offset(master, load_audio(path, SR, s, win))
            offs.append((pos - s, conf))
        off = offs[0][0]
        conf = min(o[1] for o in offs)
        drift = (offs[1][0] - offs[0][0]) * 1000
        res["cams"][name] = {"video": path, "duration": cdur, "video_offset": round(off, 4),
                             "confidence": round(conf, 1), "drift_ms": round(drift, 1)}
        flag = "  ⚠ 수동 확인" if conf < 4 or abs(drift) > 40 else ""
        print(f"{name}: offset {off:+.3f}s  conf {conf:.1f}  drift {drift:+.0f}ms{flag}")
    save_json(res, a.out)
    print(f"→ {a.out}")


if __name__ == "__main__":
    main()
