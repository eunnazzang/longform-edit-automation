#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""말하는 사람의 얼굴 타임라인을 만든다 — 여러 명이 한 화면에 있을 때 화자를 따라가기 위함.

얼굴이 여럿 잡히는 프레임에서 '입 주변이 가장 많이 움직인 얼굴'을 화자로 본다.
출력 형식은 face_timeline.py 와 같아서(0.5초 간격) shorts_premiere.py --faces 에 그대로 넣으면 된다.

사용:  speaker_timeline.py <영상.mp4> <출력.json> [클립정의.json]
       클립정의.json 을 주면 그 구간만 계산한다(그 밖은 null — 훨씬 빠르다).
출력:  [[초, [x,y,w,h,conf] 또는 null], ...]   (좌표는 640x360 스케일)
"""
import sys, os, json, subprocess, tempfile, glob

FPS = 6                 # 입 움직임을 보려면 0.5초 간격으로는 부족하다
STEP = 0.5              # 출력 간격(face_timeline.py 와 동일)
W, H = 640, 360


def scanner_path():
    here = os.path.dirname(os.path.abspath(__file__))
    exe = os.path.join(here, "facescan")
    if not os.path.exists(exe):
        print("facescan 컴파일 중(최초 1회)...")
        subprocess.run(["swiftc", "-O", "-o", exe, os.path.join(here, "facescan.swift")], check=True)
    return exe


def scan_range(src, t0, t1):
    """[t0,t1) 구간을 FPS로 뽑아 (프레임시각, 얼굴목록, 그레이 이미지) 목록 반환."""
    import numpy as np
    from PIL import Image
    tmp = tempfile.mkdtemp(prefix="spk_")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}",
                    "-i", src, "-vf", f"fps={FPS},scale={W}:{H}",
                    os.path.join(tmp, "f%05d.png")], check=True)
    faces_by_file = {}
    r = subprocess.run([scanner_path(), tmp], capture_output=True, text=True, check=True)
    for line in r.stdout.splitlines():
        d = json.loads(line)
        faces_by_file[d["f"]] = [f for f in d["faces"] if f[3] >= 30 and f[4] >= 0.4]
    frames = []
    for path in sorted(glob.glob(os.path.join(tmp, "*.png"))):
        name = os.path.basename(path)
        idx = int(name[1:6])
        g = np.asarray(Image.open(path).convert("L"), dtype=float)
        frames.append((t0 + (idx - 1) / FPS, faces_by_file.get(name, []), g))
        os.remove(path)
    os.rmdir(tmp)
    return frames


def mouth_energy(g0, g1, box):
    """얼굴 박스의 입 주변(아래 55~95%, 가운데 60%)에서 프레임 간 변화량."""
    import numpy as np
    x, y, w, h = box[0], box[1], box[2], box[3]
    x0 = int(max(0, x + w * 0.20)); x1 = int(min(W, x + w * 0.80))
    y0 = int(max(0, y + h * 0.55)); y1 = int(min(H, y + h * 0.95))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return 0.0
    a = g0[y0:y1, x0:x1]; b = g1[y0:y1, x0:x1]
    return float(np.abs(a - b).mean())


def pick_speakers(frames):
    """0.5초 창마다 입이 가장 많이 움직인 얼굴을 고른다 → [(시각, 박스|None), ...]."""
    import numpy as np
    per_win = {}
    for i in range(1, len(frames)):
        t, faces, g = frames[i]
        _, prev_faces, g_prev = frames[i - 1]
        if not faces:
            continue
        # 카메라 흔들림 보정: 화면 전체 변화량을 빼고 본다
        base = float(np.abs(g - g_prev).mean())
        win = round(t / STEP) * STEP
        slot = per_win.setdefault(win, [])
        for b in faces:
            # 직전 프레임에서 같은 얼굴(중심 거리 가까움)이 있어야 비교가 성립
            cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
            near = [p for p in prev_faces
                    if abs(p[0] + p[2] / 2 - cx) < b[2] * 0.6 and abs(p[1] + p[3] / 2 - cy) < b[3] * 0.6]
            if not near:
                continue
            e = mouth_energy(g_prev, g, b) - base * 0.6
            slot.append((e, b))
    out = []
    prev_cx = None
    for win in sorted(per_win):
        cands = per_win[win]
        if not cands:
            continue
        # 같은 얼굴이 여러 프레임에 나오므로 위치로 묶어 합산
        groups = []
        for e, b in cands:
            cx = b[0] + b[2] / 2
            for gp in groups:
                if abs(gp["cx"] - cx) < max(30, b[2] * 0.6):
                    gp["e"] += e; gp["boxes"].append(b); gp["cx"] = gp["boxes"][-1][0] + gp["boxes"][-1][2] / 2
                    break
            else:
                groups.append(dict(cx=cx, e=e, boxes=[b]))
        best = max(groups, key=lambda gp: gp["e"])
        # 관성: 직전 화자가 근소한 차이로 진 것뿐이면 화자를 바꾸지 않는다
        # (듣는 사람이 웃거나 끄덕일 때 화면이 넘어가는 걸 막는다)
        if prev_cx is not None and best["e"] > 0:
            keep = next((gp for gp in groups if abs(gp["cx"] - prev_cx) < 60), None)
            if keep is not None and keep is not best and keep["e"] >= best["e"] * 0.7:
                best = keep
        prev_cx = best["cx"]
        big = max(best["boxes"], key=lambda b: b[3])
        out.append((round(win, 2), big))
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    src, out_path = sys.argv[1], sys.argv[2]
    ranges = []
    if len(sys.argv) > 3:
        for c in json.load(open(sys.argv[3], encoding="utf-8")):
            ranges.append((max(0.0, float(c["start"]) - 1.0), float(c.get("end_exact", c["end"])) + 1.0))
    else:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", src], capture_output=True, text=True)
        ranges = [(0.0, float(r.stdout.strip()))]

    found = {}
    for t0, t1 in ranges:
        frames = scan_range(src, t0, t1)
        for t, b in pick_speakers(frames):
            found[round(t, 1)] = b
        print(f"  {t0:.0f}~{t1:.0f}s: 화자 {len(found)}개 누적")

    end = max(t1 for _, t1 in ranges)
    tl, t = [], 0.0
    while t <= end + 1e-6:
        tl.append([round(t, 1), found.get(round(t, 1))])
        t += STEP
    json.dump(tl, open(out_path, "w", encoding="utf-8"))
    n = sum(1 for _, b in tl if b)
    print(f"화자 타임라인 {len(tl)}개(검출 {n}) → {out_path}")


if __name__ == "__main__":
    main()
