"""업로드 이력 장부. 엑셀 기록이 실패해도 같은 영상이 중복 업로드되지 않도록 하는 안전장치."""
from __future__ import annotations

import json
from pathlib import Path

from settings import LOGS_DIR, now_str


class Journal:
    def __init__(self, path: Path | None = None):
        self.path = path or (LOGS_DIR / "journal.json")
        self.data: dict = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.data = {}

    def _key(self, fingerprint: str, platform: str) -> str:
        return f"{fingerprint}|{platform}"

    def done(self, fingerprint: str, platform: str) -> dict | None:
        return self.data.get(self._key(fingerprint, platform))

    def record(self, fingerprint: str, platform: str, url: str, filename: str) -> None:
        self.data[self._key(fingerprint, platform)] = {
            "url": url,
            "filename": filename,
            "time": now_str(),
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
