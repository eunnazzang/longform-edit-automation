#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""편집결정.json → 완성 롱폼 MP4 (+ 프리미어용 XML).

사용:
  render.py 편집자료/편집결정.json --subs 편집자료/자막.json \\
            --out "편집본/제목_1차 편집본.mp4" --work 편집자료/렌더캐시 [--xml] [--jobs 3] [--height 540]

  --height 540 : 1차본(확인용) 저해상도 렌더. 자막·로고·줌은 같은 비율로 줄어든다.
                 2차본부터는 빼면 편집결정의 width×height(기본 촬영본과 동일)로 렌더한다.

처리 순서:
  ① 컷마다 영상 조각 렌더(줌·구도·색보정·fps 통일) — 렌더캐시에 해시로 저장, 안 바뀐 컷은 재사용
  ② 조각 이어붙이기
  ③ 마스터 사운드에서 컷 구간을 잘라 이어붙임(컷 경계 8ms 페이드로 틱 제거)
  ④ 목소리 보정: 하이패스 → 노이즈 제거(afftdn) → 레벨 평탄화(dynaudnorm) → 라우드니스 2패스(loudnorm)
  ⑤ BGM(목소리에 자동 덕킹) + 효과음 믹스, 리미터
  ⑥ 자막(ASS) 번인 + 로고 오버레이 + 최종 인코딩
편집결정 형식은 ../references/편집결정_예시.json 참고.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import (FFMPEG, default_font, load_audio, load_json, probe, resolve, run, save_json,  # noqa: E402
                    timeline)

SR = 48000


# ---------- ① 영상 조각 ----------

def video_filter(edl: dict, cut: dict, src: dict, edl_path: str) -> str:
    W, H, fps = edl.get("width", 1920), edl.get("height", 1080), edl.get("fps", 30)
    f = []
    z = float(cut.get("zoom", 1.0))
    z1 = cut.get("zoom_to")
    cx, cy = cut.get("cx", 0.5), cut.get("cy", 0.5)
    if z1 is not None and abs(float(z1) - z) > 0.001:
        # 줌인·줌아웃 애니메이션: 컷 길이 동안 zoom → zoom_to (ease-in-out)
        z1, d = float(z1), max(cut["dur"], 0.04)
        e = f"(0.5-0.5*cos(PI*min(t/{d:.4f},1)))"
        f += [f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos", f"crop={W}:{H}",
              f"scale=w='trunc({W}*({z}+({z1 - z:.4f})*{e})/2)*2':h=-2:eval=frame:flags=bicubic",
              f"crop={W}:{H}:x='max(0,min(iw-ow,{cx}*iw-ow/2))':y='max(0,min(ih-oh,{cy}*ih-oh/2))'"]
    else:
        if z > 1.001:
            f.append(f"crop=w=iw/{z}:h=ih/{z}:x='max(0,min(iw-ow,{cx}*iw-ow/2))'"
                     f":y='max(0,min(ih-oh,{cy}*ih-oh/2))'")
        f += [f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos", f"crop={W}:{H}"]
    f.append("setsar=1")
    g = src.get("grade", {})
    if g.get("rgb"):
        ch = [f"{n}='clip(val*{a}{b:+},0,255)'" for n, (a, b) in zip("rgb", g["rgb"])]
        f.append("lutrgb=" + ":".join(ch))
    if g.get("eq"):
        f.append("eq=" + g["eq"])
    if g.get("lut"):
        f.append(f"lut3d=file='{resolve(edl_path, g['lut'])}'")
    f += [f"fps={fps}", "format=yuv420p"]
    return ",".join(f)


def render_segment(edl, edl_path, cut, work) -> str:
    src = edl["sources"][cut["cam"]]
    path = resolve(edl_path, src["video"])
    cam_in = cut["in"] - src.get("video_offset", 0)
    if cam_in < 0:
        raise SystemExit(f"컷 {cut['idx']}: 카메라 {cut['cam']} 녹화 시작 전 구간(cam_t={cam_in:.2f})")
    if cam_in + cut["dur"] > src["_duration"] + 0.02:
        raise SystemExit(f"컷 {cut['idx']}: 카메라 {cut['cam']} 녹화 끝({src['_duration']:.2f}s) 이후 구간"
                         f"(cam_t {cam_in:.2f}~{cam_in + cut['dur']:.2f})")
    vf = video_filter(edl, cut, src, edl_path)
    key = hashlib.md5(json.dumps([path, os.path.getmtime(path), round(cam_in, 4), cut["frames"], vf],
                                 ensure_ascii=False).encode()).hexdigest()[:16]
    out = os.path.join(work, f"seg_{key}.mp4")
    if os.path.exists(out):
        return out
    tmp = out + ".part.mp4"
    run([FFMPEG, "-v", "error", "-y", "-ss", f"{cam_in:.4f}", "-i", path, "-an", "-vf", vf,
         "-frames:v", str(cut["frames"]), "-c:v", "libx264", "-preset", "fast", "-crf", "14",
         "-g", str(int(edl.get("fps", 30)) * 2), "-video_track_timescale", "90000", "-threads", "4", tmp])
    os.replace(tmp, out)
    return out


# ---------- ③④ 목소리 ----------

def build_voice(edl, edl_path, cuts, work) -> str:
    master = resolve(edl_path, edl["master_audio"])
    raw = os.path.join(work, "voice_raw.wav")
    p = subprocess.Popen([FFMPEG, "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                          "-c:a", "pcm_f32le", raw], stdin=subprocess.PIPE)
    fade = int(SR * 0.008)
    ramp = np.linspace(0, 1, fade, dtype=np.float32)
    for c in cuts:
        n = int(round(c["t1"] * SR)) - int(round(c["t0"] * SR))
        if c.get("mute"):  # 타이틀·엔드카드처럼 원본 소리가 없는 컷
            x = np.zeros(n, dtype=np.float32)
        else:
            x = load_audio(master, SR, c["in"], n / SR + 0.05)[:n]
        if len(x) < n:
            x = np.pad(x, (0, n - len(x)))
        x = x.copy()
        x[:fade] *= ramp
        x[-fade:] *= ramp[::-1]
        p.stdin.write(x.astype(np.float32).tobytes())
    p.stdin.close()
    p.wait()

    a = edl.get("audio", {})
    chain = [f"highpass=f={a.get('highpass', 80)}"]
    if a.get("denoise", 12):
        chain.append(f"afftdn=nr={a.get('denoise', 12)}:nf=-50:tn=1")
    if a.get("level", True):
        chain.append("dynaudnorm=f=250:g=15:p=0.9:m=8:r=0.5")
    pre = ",".join(chain)
    I, TP, LRA = a.get("voice_lufs", -16), -1.5, 11
    m = subprocess.run([FFMPEG, "-hide_banner", "-i", raw, "-af", f"{pre},loudnorm=I={I}:TP={TP}:LRA={LRA}"
                        ":print_format=json", "-f", "null", "-"], capture_output=True, text=True).stderr
    j = json.loads(m[m.rfind("{"):m.rfind("}") + 1])
    ln = (f"loudnorm=I={I}:TP={TP}:LRA={LRA}:measured_I={j['input_i']}:measured_TP={j['input_tp']}"
          f":measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}"
          ":linear=true")
    voice = os.path.join(work, "voice.wav")
    run([FFMPEG, "-v", "error", "-y", "-i", raw, "-af", f"{pre},{ln},aresample={SR}", "-c:a", "pcm_s24le", voice])
    return voice


# ---------- ⑤ 믹스 ----------

def build_mix(edl, edl_path, voice, total, work) -> str:
    a = edl.get("audio", {})
    bgm, sfx = a.get("bgm", []), a.get("sfx", [])
    out = os.path.join(work, "mix.wav")
    if not bgm and not sfx:
        run([FFMPEG, "-v", "error", "-y", "-i", voice, "-ac", "2", "-c:a", "pcm_s24le", out])
        return out
    inputs, fc, k = ["-i", voice], ["[0:a]aformat=channel_layouts=stereo,asplit=2[v][vsc]"], 1
    blabels = []
    for b in bgm:
        inputs += ["-stream_loop", "-1", "-i", resolve(edl_path, b["file"])]
        d = b.get("end", total) - b["start"]
        fd = b.get("fade", 1.5)
        fc.append(f"[{k}:a]atrim=start={b.get('src_start', 0)}:duration={d},asetpts=PTS-STARTPTS,"
                  f"aformat=sample_rates={SR}:channel_layouts=stereo,"
                  f"afade=t=in:d={fd},afade=t=out:st={max(d - fd, 0)}:d={fd},"
                  f"volume={b.get('gain_db', -22)}dB,adelay={int(b['start'] * 1000)}:all=1[b{k}]")
        blabels.append(f"[b{k}]")
        k += 1
    mixes = ["[v]"]
    if blabels:
        fc.append("".join(blabels) + f"amix=inputs={len(blabels)}:normalize=0:duration=longest[bg]")
        duck = a.get("duck", {})
        fc.append(f"[bg][vsc]sidechaincompress=threshold={duck.get('threshold', 0.03)}"
                  f":ratio={duck.get('ratio', 6)}:attack=30:release={duck.get('release', 500)}[bgd]")
        mixes.append("[bgd]")
    else:
        fc.append("[vsc]anullsink")
    slabels = []
    for s in sfx:
        inputs += ["-i", resolve(edl_path, s["file"])]
        fc.append(f"[{k}:a]aformat=sample_rates={SR}:channel_layouts=stereo,volume={s.get('gain_db', -6)}dB,"
                  f"adelay={int(s['at'] * 1000)}:all=1[s{k}]")
        slabels.append(f"[s{k}]")
        k += 1
    if slabels:
        fc.append("".join(slabels) + f"amix=inputs={len(slabels)}:normalize=0:duration=longest[sx]")
        mixes.append("[sx]")
    fc.append("".join(mixes) + f"amix=inputs={len(mixes)}:normalize=0:duration=first,"
              f"atrim=duration={total},alimiter=limit=0.89:level=false[out]")
    run([FFMPEG, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[out]",
         "-c:a", "pcm_s24le", out])
    return out


# ---------- ⑥ 자막 ----------

def ass_color(c: str) -> str:
    c = c.lstrip("#")
    r, g, b = c[0:2], c[2:4], c[4:6]
    alpha = 255 - int(c[6:8], 16) if len(c) == 8 else 0
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def font_family(path: str) -> str:
    from PIL import ImageFont
    return ImageFont.truetype(path, 10).getname()[0]


def ass_time(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass(edl, edl_path, subs, work) -> tuple[str, str]:
    W, H = edl.get("_playres", (edl.get("width", 1920), edl.get("height", 1080)))
    fonts = os.path.join(work, "fonts")
    os.makedirs(fonts, exist_ok=True)
    # 기본 자막: 프리텐다드 Bold, 흰 글자 + 검정 외곽선 + 살짝 그림자 (에셋이 없을 때)
    base = {"size": round(H * 0.054), "color": "#FFFFFF", "outline_color": "#000000", "outline": max(2, round(H / 270)),
            "shadow": max(1, round(H / 540)), "shadow_color": "#00000080", "bold": True, "align": 2,
            "margin_v": round(H * 0.065), **edl.get("style", {})}
    styles = {"Default": base, **{n: {**base, **s} for n, s in edl.get("styles", {}).items()}}
    lines = []
    for name, s in styles.items():
        fam = s.get("font", "Pretendard")
        ff = resolve(edl_path, s["font_file"]) if s.get("font_file") else (None if s.get("font") else default_font())
        if ff and not os.path.exists(ff):
            print(f"⚠ 자막 폰트 파일 없음: {ff} — 기본 폰트로 대체")
            ff = default_font()
        if ff:
            shutil.copy(ff, fonts)
            fam = font_family(ff)
        box = s.get("box", False)
        lines.append(
            f"Style: {name},{fam},{s.get('size', 58)},{ass_color(s.get('color', '#FFFFFF'))},&H000000FF,"
            f"{ass_color(s.get('outline_color', '#000000'))},"
            f"{ass_color(s.get('box_color', '#00000099') if box else s.get('shadow_color', '#00000080'))},"
            f"{-1 if s.get('bold', True) else 0},0,0,0,100,100,{s.get('spacing', 0)},0,{3 if box else 1},"
            f"{s.get('outline', 4)},{s.get('shadow', 0)},{s.get('align', 2)},"
            f"{s.get('margin_lr', 80)},{s.get('margin_lr', 80)},{s.get('margin_v', 70)},1")
    ev = []
    for it in subs:
        t = it["text"].replace("{", "(").replace("}", ")").replace("\n", "\\N")
        ev.append(f"Dialogue: 0,{ass_time(it['start'])},{ass_time(it['end'])},{it.get('style', 'Default')},,0,0,0,,{t}")
    ass = os.path.join(work, "subs.ass")
    with open(ass, "w", encoding="utf-8") as f:
        f.write(f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n"
                "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
                "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
                "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n" + "\n".join(lines) +
                "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                + "\n".join(ev) + "\n")
    return ass, fonts


def logo_xy(lg: dict) -> str:
    m = lg.get("margin", 40)
    return {"top-right": f"W-w-{m}:{m}", "top-left": f"{m}:{m}", "bottom-right": f"W-w-{m}:H-h-{m}",
            "bottom-left": f"{m}:H-h-{m}"}.get(lg.get("pos", "top-right"), lg.get("pos"))


# ---------- 프리미어 XML ----------

def write_xml(edl, edl_path, cuts, path):
    from xml.sax.saxutils import escape
    fps = edl.get("fps", 30)
    tb, ntsc = int(round(fps)), "TRUE" if abs(fps - round(fps)) > 0.01 else "FALSE"
    rate = f"<rate><timebase>{tb}</timebase><ntsc>{ntsc}</ntsc></rate>"
    master = resolve(edl_path, edl["master_audio"])
    files, vitems, aitems = {}, [], []

    def fileref(p, has_video):
        if p in files:
            return f'<file id="{files[p]}"/>'
        fid = files[p] = f"file-{len(files) + 1}"
        info = probe(p)
        media = ""
        if has_video:
            media += (f"<video><samplecharacteristics><width>{info['width']}</width>"
                      f"<height>{info['height']}</height></samplecharacteristics></video>")
        media += "<audio><channelcount>1</channelcount></audio>"
        return (f'<file id="{fid}"><name>{escape(os.path.basename(p))}</name>'
                f"<pathurl>file://{escape(p)}</pathurl>{rate}<duration>{int(info['duration'] * tb)}</duration>"
                f"<media>{media}</media></file>")

    for c in cuts:
        src = edl["sources"][c["cam"]]
        vp = resolve(edl_path, src["video"])
        s, e = int(round(c["t0"] * tb)), int(round(c["t1"] * tb))
        vin = int(round((c["in"] - src.get("video_offset", 0)) * tb))
        ain = int(round(c["in"] * tb))
        vitems.append(f'<clipitem id="v{c["idx"]}"><name>{escape(c.get("note", c["cam"]))}</name>{rate}'
                      f"<start>{s}</start><end>{e}</end><in>{vin}</in><out>{vin + e - s}</out>"
                      f"{fileref(vp, True)}</clipitem>")
        if c.get("mute"):
            continue
        aitems.append(f'<clipitem id="a{c["idx"]}"><name>voice</name>{rate}<start>{s}</start><end>{e}</end>'
                      f"<in>{ain}</in><out>{ain + e - s}</out>{fileref(master, False)}"
                      "<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack></clipitem>")
    total = int(round(cuts[-1]["t1"] * tb))
    W, H = edl.get("width", 1920), edl.get("height", 1080)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4"><sequence>'
           f"<name>{escape(edl.get('title', '롱폼'))}</name>{rate}<duration>{total}</duration><media>"
           f"<video><format><samplecharacteristics><width>{W}</width><height>{H}</height>"
           f"{rate}</samplecharacteristics></format><track>{''.join(vitems)}</track></video>"
           f"<audio><track>{''.join(aitems)}</track></audio></media></sequence></xmeml>\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("edl")
    ap.add_argument("--subs", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--xml", action="store_true", help="프리미어용 컷 타임라인 XML도 만든다")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--height", type=int, default=None, help="저해상도 확인용 렌더 높이(예: 540)")
    a = ap.parse_args()

    edl = load_json(a.edl)
    W0, H0 = edl.get("width", 1920), edl.get("height", 1080)
    edl["_playres"] = (W0, H0)
    k = 1.0
    if a.height and a.height < H0:
        k = a.height / H0
        edl["width"], edl["height"] = int(round(W0 * k / 2)) * 2, a.height
        if edl.get("logo"):
            for key, dv in (("width", 160), ("margin", 40)):
                edl["logo"][key] = max(1, int(round(edl["logo"].get(key, dv) * k)))
        print(f"확인용 저해상도 렌더: {edl['width']}x{edl['height']} (원래 {W0}x{H0})")
    cuts = timeline(edl)
    total = cuts[-1]["t1"]
    os.makedirs(a.work, exist_ok=True)
    for src in edl["sources"].values():
        src["_duration"] = probe(resolve(a.edl, src["video"]))["duration"]
    print(f"컷 {len(cuts)}개, 총 {total / 60:.1f}분")

    print("① 영상 조각 렌더…")
    with ThreadPoolExecutor(a.jobs) as ex:
        segs = list(ex.map(lambda c: render_segment(edl, a.edl, c, a.work), cuts))
    lst = os.path.join(a.work, "concat.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.writelines(f"file '{os.path.abspath(s)}'\n" for s in segs)
    video = os.path.join(a.work, "video.mp4")
    print("② 이어붙이기…")
    run([FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", video])

    print("③④ 목소리 정리…")
    voice = build_voice(edl, a.edl, cuts, a.work)
    print("⑤ BGM·효과음 믹스…")
    mix = build_mix(edl, a.edl, voice, total, a.work)

    print("⑥ 자막·로고·최종 인코딩…")
    inputs, chain, vlab = ["-i", video, "-i", mix], [], "0:v"
    if a.subs:
        ass, fonts = write_ass(edl, a.edl, load_json(a.subs)["items"], a.work)
        # 경로에 공백·한글이 있어 필터 안에서 깨지기 쉽다 — 작업 폴더에서 상대 경로로 부른다
        chain.append(f"[{vlab}]ass=subs.ass:fontsdir=fonts[vs]")
        vlab = "vs"
    lg = edl.get("logo")
    if lg:
        inputs += ["-loop", "1", "-i", resolve(a.edl, lg["file"])]
        chain.append(f"[2:v]scale={lg.get('width', 160)}:-1,format=rgba,"
                     f"colorchannelmixer=aa={lg.get('opacity', 1.0)}[lg]")
        chain.append(f"[{vlab}][lg]overlay={logo_xy(lg)}:shortest=1[vl]")
        vlab = "vl"
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".part.mp4"
    vmap = ["-filter_complex", ";".join(chain), "-map", f"[{vlab}]"] if chain else ["-map", "0:v"]
    run([FFMPEG, "-v", "error", "-y", *[os.path.abspath(x) if os.path.exists(x) else x for x in inputs],
         *vmap, "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf),
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", "-t", f"{total:.3f}",
         "-movflags", "+faststart", tmp], cwd=a.work)
    os.replace(tmp, out)

    if a.xml:
        xp = os.path.join(os.path.dirname(os.path.abspath(a.edl)),
                          re.sub(r"[\\/]", "_", edl.get("title", "롱폼")) + "_타임라인.xml")
        write_xml(edl, a.edl, cuts, xp)
        print(f"XML → {xp}")
    save_json({"out": out, "duration": total, "cuts": len(cuts),
               "cut_bounds": [[c["t0"], c["t1"]] for c in cuts]}, os.path.join(a.work, "manifest.json"))
    got = probe(out)["duration"]
    print(f"완료 → {out}  ({got:.2f}s / 예정 {total:.2f}s)")
    if abs(got - total) > 0.2:
        print("⚠ 길이가 예정과 다르다 — qc.py로 확인")


if __name__ == "__main__":
    main()
