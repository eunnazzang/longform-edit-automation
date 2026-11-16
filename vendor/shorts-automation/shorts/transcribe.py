#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""영상에서 단어 단위 전사(words.json)를 만든다 — 쇼츠 파이프라인 1단계.

사용:  python3 transcribe.py <영상.mp4> [출력.json]
요구:  ffmpeg, mlx-whisper (Apple Silicon 전용. pip install mlx-whisper)
"""
import sys, os, json, subprocess, tempfile

MODEL = "mlx-community/whisper-large-v3-turbo"      # 한국어 정확+빠름

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + "_words.json"
    # 임시 파일 이름은 프로세스마다 달라야 한다(여러 영상을 동시에 돌리면 서로 지워버린다)
    fd, wav = tempfile.mkstemp(prefix="transcribe_", suffix=".wav")
    os.close(fd)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-ac", "1", "-ar", "16000", wav], check=True)
    import mlx_whisper
    r = mlx_whisper.transcribe(wav, path_or_hf_repo=MODEL, word_timestamps=True,
                               language="ko", condition_on_previous_text=False)
    words = []
    for seg in r["segments"]:
        for w in seg.get("words", []):
            t = w["word"].strip()
            if t:
                words.append([round(w["start"], 2), round(w["end"], 2), t])
    json.dump(words, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    os.remove(wav)
    print(f"단어 {len(words)}개 → {out}")

if __name__ == "__main__":
    main()
