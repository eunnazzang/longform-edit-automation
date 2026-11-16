#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""영상 전체의 얼굴 타임라인(0.5초 샘플)을 만든다 — 풀프레임 소스용 크롭 근거.

macOS Vision 프레임워크(facescan.swift)를 사용한다. 첫 실행 시 자동 컴파일.
사용:  python3 face_timeline.py <영상.mp4> [출력.json]
출력:  [[초, [x,y,w,h,conf] 또는 null], ...]  (좌표는 640x360 스케일 — 소스 1080p면 x3)
"""
import sys, os, json, subprocess, tempfile, glob

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + "_faces.json"
    here = os.path.dirname(os.path.abspath(__file__))
    scanner = os.path.join(here, "facescan")
    if not os.path.exists(scanner):
        print("facescan 컴파일 중(최초 1회)...")
        subprocess.run(["swiftc", "-O", "-o", scanner, os.path.join(here, "facescan.swift")], check=True)
    tmp = tempfile.mkdtemp(prefix="facescan_")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                    "-vf", "fps=2,scale=640:360", os.path.join(tmp, "f%04d.png")], check=True)
    r = subprocess.run([scanner, tmp], capture_output=True, text=True, check=True)
    frames = []
    for line in r.stdout.splitlines():
        d = json.loads(line)
        idx = int(d["f"][1:5]); t = (idx - 1) * 0.5
        real = [f for f in d["faces"] if f[3] >= 40 and f[4] >= 0.5]
        big = max(real, key=lambda f: f[3]) if real else None
        frames.append([t, big])
    json.dump(frames, open(out, "w", encoding="utf-8"))
    for f in glob.glob(os.path.join(tmp, "*.png")):
        os.remove(f)
    os.rmdir(tmp)
    n_face = sum(1 for _, b in frames if b)
    print(f"프레임 {len(frames)}개(얼굴 {n_face}) → {out}")

if __name__ == "__main__":
    main()
