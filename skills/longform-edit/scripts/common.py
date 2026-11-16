# -*- coding: utf-8 -*-
"""롱폼 편집 스크립트 공용 함수."""
from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata

import numpy as np

LF_HOME = os.environ.get("LONGFORM_HOME", os.path.expanduser("~/.longform-edit"))
BIN = os.path.expanduser("~/.local/bin")
FFMPEG = os.path.join(BIN, "ffmpeg") if os.path.exists(os.path.join(BIN, "ffmpeg")) else "ffmpeg"
FFPROBE = os.path.join(BIN, "ffprobe") if os.path.exists(os.path.join(BIN, "ffprobe")) else "ffprobe"


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def probe(path: str) -> dict:
    out = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format",
                          "-show_streams", path], check=True, capture_output=True).stdout
    info = json.loads(out)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    r = {"path": path, "duration": float(info["format"].get("duration", 0))}
    if v:
        num, den = v.get("avg_frame_rate", "0/1").split("/")
        r.update(width=v["width"], height=v["height"],
                 fps=round(float(num) / float(den), 3) if float(den) else 0)
    if a:
        r.update(sample_rate=int(a["sample_rate"]), channels=a["channels"])
    return r


def load_audio(path: str, sr: int = 8000, start: float = 0, dur: float | None = None) -> np.ndarray:
    """모노 float32 PCM으로 읽는다."""
    cmd = [FFMPEG, "-v", "error", "-ss", str(start)]
    if dur:
        cmd += ["-t", str(dur)]
    cmd += ["-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(obj, path: str):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def resolve(base_json: str, p: str) -> str:
    """편집결정.json 안의 상대 경로는 프로젝트 폴더(편집자료/의 부모) 기준이다."""
    if os.path.isabs(p):
        return p
    proj = os.path.dirname(os.path.dirname(os.path.abspath(base_json)))
    return os.path.join(proj, p)


def timeline(edl: dict) -> list[dict]:
    """컷마다 타임라인 위치를 프레임 단위로 계산한다. 오디오·자막도 이 값을 따른다."""
    fps = edl.get("fps", 30)
    t_frames = 0
    out = []
    for i, c in enumerate(edl["cuts"]):
        n = int(round((c["out"] - c["in"]) * fps))
        if n <= 0:
            raise SystemExit(f"컷 {i}: out <= in ({c})")
        out.append({**c, "idx": i, "frames": n, "t0": t_frames / fps,
                    "t1": (t_frames + n) / fps, "dur": n / fps})
        t_frames += n
    return out


def ts(sec: float) -> str:
    m, s = divmod(max(sec, 0), 60)
    h, m = divmod(int(m), 60)
    return f"{h:d}:{m:02d}:{s:05.2f}" if h else f"{m:02d}:{s:05.2f}"


_PUNCT = re.compile(r"[.,!?…\"'“”‘’·]")


def strip_punct(s: str) -> str:
    return _PUNCT.sub("", s).strip()


# ---------- 설치 설정 (install.sh 가 ~/.longform-edit/config.json 에 쓴다) ----------

def config() -> dict:
    p = os.path.join(LF_HOME, "config.json")
    cfg = {"projects_root": os.path.expanduser("~/Movies/롱폼제작")}
    if os.path.exists(p):
        cfg.update(load_json(p))
    cfg.setdefault("feedback_log", os.path.join(cfg["projects_root"], "피드백기록.md"))
    return cfg


def default_font(weight: str = "Bold") -> str | None:
    """기본 자막 폰트(프리텐다드) 파일 경로. 에셋에 폰트가 없을 때 쓴다."""
    for d in (os.path.join(LF_HOME, "fonts"), os.path.expanduser("~/Library/Fonts"), "/Library/Fonts"):
        f = os.path.join(d, f"Pretendard-{weight}.otf")
        if os.path.exists(f):
            return f
    return None


# 프로젝트 폴더 4개 (사용자 규칙 — 이 밖에는 아무것도 만들지 않는다)
SHOOT, EDITS, WORK, ASSETS = "촬영본", "편집본", "편집자료", "에셋"
