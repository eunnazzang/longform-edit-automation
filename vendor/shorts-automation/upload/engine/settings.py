"""공통 설정·경로·로거. 모든 모듈이 여기서 경로와 설정을 가져온다."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("AUTOUP_ROOT") or Path(__file__).resolve().parent.parent)

PENDING_DIR = PROJECT_ROOT / "업로드대기"
DONE_DIR = PROJECT_ROOT / "업로드완료"
LOGS_DIR = PROJECT_ROOT / "logs"
CONFIG_DIR = PROJECT_ROOT / "config"
EXCEL_PATH = PROJECT_ROOT / "업로드목록.xlsx"
CONFIG_PATH = CONFIG_DIR / "config.json"

YOUTUBE_CLIENT_SECRET = CONFIG_DIR / "client_secret.json"
YOUTUBE_TOKEN = CONFIG_DIR / "youtube_token.json"
INSTAGRAM_TOKEN = CONFIG_DIR / "instagram_token.json"
TIKTOK_PROFILE_DIR = CONFIG_DIR / "tiktok_profile"

PLATFORMS = ["유튜브", "인스타"]
RESULT_COLUMNS = {"유튜브": "유튜브결과", "인스타": "인스타결과"}

DEFAULT_CONFIG = {
    "default_platforms": "전체",
    "default_visibility": "공개",
    "default_hashtags": "",
    "interval_minutes": 30,
    "instagram_api_version": "v23.0",
    "pending_dir": "",   # 비우면 프로젝트 안 '업로드대기' 폴더 사용
    "done_dir": "",      # 비우면 pending_dir 안 '업로드완료' 폴더(외부 경로) 또는 프로젝트 '업로드완료'
}


def get_pending_dir(config: dict) -> Path:
    p = str(config.get("pending_dir") or "").strip()
    return Path(p).expanduser() if p else PENDING_DIR


def get_done_dir(config: dict) -> Path:
    p = str(config.get("done_dir") or "").strip()
    if p:
        return Path(p).expanduser()
    pending = get_pending_dir(config)
    return (pending / "업로드완료") if pending != PENDING_DIR else DONE_DIR


def ensure_dirs() -> None:
    for d in (PENDING_DIR, DONE_DIR, LOGS_DIR, CONFIG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_dirs()
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass  # 깨진 config는 기본값으로 동작
    else:
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return cfg


_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    ensure_dirs()
    logger = logging.getLogger("autoup")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("[%(asctime)s] %(levelname)s  %(message)s", datefmt="%m-%d %H:%M:%S")
        fh = logging.FileHandler(
            LOGS_DIR / f"업로드_{datetime.now():%Y%m%d}.log", encoding="utf-8"
        )
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
    _logger = logger
    return logger


def file_fingerprint(path: Path) -> str:
    """파일 크기 + 앞/뒤 1MB 해시. 같은 파일명을 나중에 재사용해도 구분된다."""
    h = hashlib.sha1()
    size = path.stat().st_size
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(1024 * 1024))
        if size > 2 * 1024 * 1024:
            f.seek(-1024 * 1024, os.SEEK_END)
            h.update(f.read(1024 * 1024))
    return h.hexdigest()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
