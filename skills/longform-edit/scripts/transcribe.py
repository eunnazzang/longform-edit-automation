#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""촬영본 오디오 → 단어 단위 전사 json  [[시작초, 끝초, "단어"], ...]

사용:  transcribe.py <영상/오디오> <출력.json> [--glossary 편집자료/기획안/용어.txt] [--lang ko]
- Apple Silicon: mlx-whisper (whisper-large-v3-turbo, 로컬 GPU). 영상이 밖으로 나가지 않는다.
- 그 외: faster-whisper 가 설치돼 있으면 그걸 쓴다.
- --glossary: 기획안의 출연자 이름·브랜드·전문용어를 한 줄에 하나씩. 인식 힌트로 넣어 오인식을 줄인다.
  (힌트일 뿐이다 — 전사 후 기획안과 대조하는 검수는 따로 한다)
"""
from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from common import FFMPEG, save_json  # noqa: E402

MLX_MODEL = "mlx-community/whisper-large-v3-turbo"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--glossary")
    ap.add_argument("--lang", default="ko")
    a = ap.parse_args()

    prompt = None
    if a.glossary and os.path.exists(a.glossary):
        terms = [t.strip() for t in open(a.glossary, encoding="utf-8") if t.strip() and not t.startswith("#")]
        prompt = ", ".join(terms)[:600] or None

    fd, wav = tempfile.mkstemp(prefix="lf_transcribe_", suffix=".wav")
    os.close(fd)
    try:
        subprocess.run([FFMPEG, "-y", "-v", "error", "-i", a.src, "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
        words = []
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            import mlx_whisper
            r = mlx_whisper.transcribe(wav, path_or_hf_repo=MLX_MODEL, word_timestamps=True, language=a.lang,
                                       condition_on_previous_text=False, initial_prompt=prompt)
            for seg in r["segments"]:
                for w in seg.get("words", []):
                    t = w["word"].strip()
                    if t:
                        words.append([round(w["start"], 2), round(w["end"], 2), t])
        else:
            from faster_whisper import WhisperModel
            m = WhisperModel("large-v3", compute_type="int8")
            segs, _ = m.transcribe(wav, language=a.lang, word_timestamps=True, initial_prompt=prompt,
                                   condition_on_previous_text=False)
            for seg in segs:
                for w in seg.words or []:
                    t = w.word.strip()
                    if t:
                        words.append([round(w.start, 2), round(w.end, 2), t])
        save_json(words, a.out)
        print(f"단어 {len(words)}개 → {a.out}")
    finally:
        if os.path.exists(wav):
            os.remove(wav)


if __name__ == "__main__":
    main()
