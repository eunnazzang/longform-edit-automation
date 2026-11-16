#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""렌더된 편집본을 수치로 검수한다.

사용:  qc.py "편집본/제목_1차 편집본.mp4" 편집자료/편집결정.json [--subs 편집자료/자막.json] --out 편집자료/QC/1차
       [--ref 편집자료/레퍼런스/분석/분석.json]
검사:  길이(편집결정 대비) / 통합 라우드니스·피크 / 10초 구간별 라우드니스 편차 / 블랙·무음 구간 /
       컷별 평균 밝기 편차 / 자막 겹침·너무 짧은 자막·화면 밖으로 긴 자막 / (--ref) 예시 대비 컷 호흡
출력:  report.md (경고 목록), seams_NN.jpg (컷 직후 0.2초 프레임 — 색·구도·로고·자막 위치를 눈으로 확인)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import FFMPEG, load_json, probe, save_json, timeline, ts  # noqa: E402
from ref_analyze import contact_sheets, loudness  # noqa: E402


def short_term(path: str) -> np.ndarray:
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path, "-vn", "-af", "ebur128=framelog=verbose",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    return np.array([[float(t), float(s)] for t, s in re.findall(r"t:\s*([\d.]+).*?S:\s*(-?[\d.]+)", p)])


def detect(path: str, filt: str, key: str, video: bool) -> list[tuple[float, float]]:
    args = ["-an", "-vf", filt] if video else ["-vn", "-af", filt]
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path, *args, "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    if video:
        return [(float(s), float(e)) for s, e in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", p)]
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", p)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p)]
    return list(zip(st, en))


def luma(path: str, times: list[float]) -> list[float]:
    out = []
    for t in times:
        raw = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                              "-vf", "scale=160:90", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True).stdout
        out.append(float(np.frombuffer(raw, np.uint8).mean()) if raw else float("nan"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video"); ap.add_argument("edl")
    ap.add_argument("--subs", default=None)
    ap.add_argument("--ref", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    edl = load_json(a.edl)
    cuts = timeline(edl)
    exp = cuts[-1]["t1"]
    info = probe(a.video)
    warn, facts = [], {}

    facts["duration"] = round(info["duration"], 2)
    facts["expected"] = round(exp, 2)
    if abs(info["duration"] - exp) > 0.2:
        warn.append(f"길이 불일치: {info['duration']:.2f}s (예정 {exp:.2f}s) — 렌더 중단 의심")

    print("라우드니스…")
    L = loudness(a.video)
    facts["loudness"] = L
    target = edl.get("audio", {}).get("voice_lufs", -16)
    if abs(L["integrated_lufs"] - target) > 1.5:
        warn.append(f"통합 라우드니스 {L['integrated_lufs']} LUFS (목표 {target})")
    if L["true_peak_dbfs"] > -1.0:
        warn.append(f"피크 {L['true_peak_dbfs']} dBFS — 클리핑 위험")
    st = short_term(a.video)
    if len(st):
        # 말하는 구간(-40 LUFS 이상)의 10초 평균끼리 비교 — 장면마다 목소리 크기가 다른지
        speech = st[st[:, 1] > -40]
        bins = {}
        for t, s in speech:
            bins.setdefault(int(t // 10), []).append(s)
        means = {k: np.mean(v) for k, v in bins.items() if len(v) > 20}
        if means:
            med = np.median(list(means.values()))
            for k, m in sorted(means.items()):
                if abs(m - med) > 3:
                    warn.append(f"{ts(k * 10)}~{ts(k * 10 + 10)} 목소리 크기 {m - med:+.1f}dB (중앙값 대비)")
            facts["speech_loudness_spread_db"] = round(float(np.ptp(list(means.values()))), 1)

    print("블랙·무음…")
    for s, e in detect(a.video, "blackdetect=d=0.1:pix_th=0.1", "black", True):
        warn.append(f"블랙 화면 {ts(s)}~{ts(e)}")
    for s, e in detect(a.video, "silencedetect=n=-45dB:d=1.5", "silence", False):
        warn.append(f"무음 {ts(s)}~{ts(e)} ({e - s:.1f}s)")

    print("컷별 밝기·이음새 시트…")
    times = [min(c["t0"] + 0.2, c["t1"] - 0.05) for c in cuts]
    Y = luma(a.video, times)
    by_cam = {}
    for c, y in zip(cuts, Y):
        by_cam.setdefault(c["cam"], []).append(y)
    facts["luma_by_cam"] = {k: round(float(np.nanmean(v)), 1) for k, v in by_cam.items()}
    if len(by_cam) > 1:
        vals = list(facts["luma_by_cam"].values())
        if max(vals) - min(vals) > 8:
            warn.append(f"카메라 간 평균 밝기 차 {max(vals) - min(vals):.0f} (0~255) — color_match 재확인")
    med = float(np.nanmedian(Y))
    for c, y in zip(cuts, Y):
        if abs(y - med) > 25:
            warn.append(f"컷 {c['idx']} ({ts(c['t0'])}) 밝기 {y:.0f} — 전체 중앙값 {med:.0f}와 차이 큼")
    labels = [f"#{c['idx']} {ts(c['t0'])} {c['cam']}" for c in cuts]
    facts["seam_sheets"] = contact_sheets(a.video, times, labels, a.out, prefix="seams")

    durs = np.array([c["dur"] for c in cuts])
    facts["cuts"] = len(cuts)
    facts["shot_mean"] = round(float(durs.mean()), 2)
    facts["cuts_per_min"] = round(len(cuts) / (exp / 60), 2)
    if a.ref:
        r = load_json(a.ref)
        facts["ref"] = {k: r[k] for k in ("shot_mean", "cuts_per_min", "loudness")}
        if abs(facts["shot_mean"] - r["shot_mean"]) > r["shot_mean"] * 0.25:
            warn.append(f"평균 컷 길이 {facts['shot_mean']}s — 예시 {r['shot_mean']}s와 25% 넘게 차이")

    if a.subs:
        items = load_json(a.subs)["items"]
        maxc = edl.get("style", {}).get("max_chars", 24)
        for p, q in zip(items, items[1:]):
            if q["start"] < p["end"] - 0.01:
                warn.append(f"자막 겹침 {ts(q['start'])}: '{p['text']}' / '{q['text']}'")
        for it in items:
            if it["end"] - it["start"] < 0.4:
                warn.append(f"너무 짧은 자막 {ts(it['start'])} '{it['text']}'")
            if len(it["text"].replace(" ", "")) > maxc and "\n" not in it["text"]:
                warn.append(f"긴 자막 {ts(it['start'])} ({len(it['text'])}자) '{it['text']}'")
            if it["end"] > exp + 0.05:
                warn.append(f"영상 끝 이후 자막 {ts(it['start'])}")
        facts["subs"] = len(items)

    save_json({"facts": facts, "warnings": warn}, os.path.join(a.out, "report.json"))
    with open(os.path.join(a.out, "report.md"), "w", encoding="utf-8") as f:
        f.write(f"# QC — {os.path.basename(a.video)}\n\n")
        f.write(f"- 길이 {facts['duration']}s (예정 {facts['expected']}s), 컷 {facts['cuts']}개, "
                f"평균 컷 {facts['shot_mean']}s, 분당 {facts['cuts_per_min']}컷\n")
        f.write(f"- 라우드니스 {L['integrated_lufs']} LUFS, LRA {L['lra']}, 피크 {L['true_peak_dbfs']} dBFS\n")
        f.write(f"- 카메라별 밝기 {facts['luma_by_cam']}\n")
        if "ref" in facts:
            f.write(f"- 예시: 평균 컷 {facts['ref']['shot_mean']}s, 분당 {facts['ref']['cuts_per_min']}컷, "
                    f"{facts['ref']['loudness']['integrated_lufs']} LUFS\n")
        f.write(f"- 이음새 시트: {', '.join(os.path.basename(s) for s in facts['seam_sheets'])}\n\n")
        f.write(f"## 경고 {len(warn)}건\n\n" + ("\n".join(f"- [ ] {w}" for w in warn) if warn else "없음") + "\n")
    print(f"경고 {len(warn)}건 → {a.out}/report.md")
    for w in warn[:30]:
        print("  -", w)


if __name__ == "__main__":
    main()
