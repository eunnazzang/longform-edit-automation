"""인스타그램 API는 영상을 '공개 URL'로만 받는다.
업로드 순간에만 내 Mac의 파일을 임시 공개 주소로 노출하는 터널.
cloudflared(있으면) → localhost.run(ssh, 기본 내장) 순서로 시도한다.
"""
from __future__ import annotations

import mimetypes
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote

import requests

from settings import PROJECT_ROOT, get_logger

CLOUDFLARED_CANDIDATES = [
    PROJECT_ROOT / "bin" / "cloudflared",
    Path("/usr/local/bin/cloudflared"),
    Path("/opt/homebrew/bin/cloudflared"),
]


def find_cloudflared() -> str | None:
    for p in CLOUDFLARED_CANDIDATES:
        if p.exists():
            return str(p)
    return shutil.which("cloudflared")


class _RangeHandler(BaseHTTPRequestHandler):
    """등록된 파일만, Range 요청 지원해서 서빙 (Meta 서버가 Range로 받아갈 수 있음)."""
    files: dict = {}
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        get_logger().debug("터널 요청: " + fmt % args)

    def _resolve(self) -> Path | None:
        return self.files.get(unquote(self.path))

    def do_HEAD(self):
        self._serve(head_only=True)

    def do_GET(self):
        self._serve(head_only=False)

    def _serve(self, head_only: bool):
        path = self._resolve()
        if path is None or not path.exists():
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        size = path.stat().st_size
        ctype = mimetypes.guess_type(str(path))[0] or "video/mp4"
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range")
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                elif m.group(2):  # bytes=-N (마지막 N바이트)
                    start = max(0, size - int(m.group(2)))
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


class FileTunnel:
    def __init__(self):
        self.log = get_logger()
        self.server: ThreadingHTTPServer | None = None
        self.port: int | None = None
        self.public_base: str | None = None
        self.proc: subprocess.Popen | None = None
        self.token = secrets.token_urlsafe(12)
        self._files: dict = {}

    # ---------- 로컬 서버 ----------
    def start_server(self) -> int:
        if self.server:
            return self.port
        handler = type("Handler", (_RangeHandler,), {"files": self._files})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.port

    def register(self, path: Path) -> str:
        """파일을 등록하고 (터널이 떠 있으면) 공개 URL을 돌려준다."""
        local_path = f"/{self.token}/{quote(path.name)}"
        self._files[f"/{self.token}/{path.name}"] = path
        self._files[local_path] = path  # quote 전/후 모두 매핑
        base = self.public_base or f"http://127.0.0.1:{self.port}"
        return f"{base}/{self.token}/{quote(path.name)}"

    # ---------- 공개 터널 ----------
    def ensure_public(self) -> bool:
        """공개 터널이 없으면 연다. 성공 여부 반환."""
        if self.public_base:
            return True
        self.start_server()
        cf = find_cloudflared()
        if cf and self._start_cloudflared(cf):
            return True
        if self._start_pinggy():
            return True
        if self._start_localhost_run():
            return True
        return False

    def _read_until(self, pattern: str, timeout: int, reject=None) -> str | None:
        """proc의 출력에서 패턴 URL을 찾는다.

        중요: URL을 찾은 뒤에도 출력을 계속 비워야 한다. (pinggy 등은 요청 로그를
        계속 찍는데, 읽지 않으면 파이프 버퍼가 가득 차 터널 프로세스가 멈춘다)
        """
        found: list = []
        got_url = threading.Event()

        def reader():
            try:
                for line in self.proc.stdout:  # 프로세스가 살아있는 동안 계속 소비
                    if not got_url.is_set():
                        self.log.debug("터널 출력: " + line.strip())
                        for m in re.finditer(pattern, line):
                            url = m.group(0)
                            if reject and reject(url):
                                continue
                            found.append(url)
                            got_url.set()
                            break
            except Exception:
                pass

        threading.Thread(target=reader, daemon=True).start()
        got_url.wait(timeout)
        return found[0] if found else None

    def _start_cloudflared(self, binary: str) -> bool:
        self.log.info("임시 공개 터널 시작 (cloudflared)...")
        try:
            self.proc = subprocess.Popen(
                [binary, "tunnel", "--url", f"http://127.0.0.1:{self.port}", "--no-autoupdate"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            url = self._read_until(r"https://[a-z0-9-]+\.trycloudflare\.com", timeout=40)
            if url:
                self.public_base = url
                self.log.info(f"터널 주소 확보: {url}")
                return True
            self._kill_proc()
        except Exception as e:
            self.log.warning(f"cloudflared 실패: {e}")
            self._kill_proc()
        return False

    def _start_pinggy(self) -> bool:
        self.log.info("임시 공개 터널 시작 (pinggy)...")
        try:
            self.proc = subprocess.Popen(
                [
                    "/usr/bin/ssh", "-p", "443",
                    "-o", "StrictHostKeyChecking=accept-new",
                    "-o", "ExitOnForwardFailure=yes",
                    "-o", "ServerAliveInterval=30",
                    "-o", "ConnectTimeout=15",
                    "-R", f"0:127.0.0.1:{self.port}",
                    "a.pinggy.io",
                ],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                stdin=subprocess.DEVNULL,
            )
            # free.pinggy.net 도메인만 사용 (pinggy-free.link 는 일부 네트워크에서 DNS 실패)
            url = self._read_until(
                r"https://[a-zA-Z0-9-]+\.free\.pinggy\.net",
                timeout=40,
            )
            if url:
                self.public_base = url
                self.log.info(f"터널 주소 확보: {url}")
                return True
            self._kill_proc()
        except Exception as e:
            self.log.warning(f"pinggy 실패: {e}")
            self._kill_proc()
        return False

    def _start_localhost_run(self) -> bool:
        self.log.info("임시 공개 터널 시작 (localhost.run)...")
        try:
            self.proc = subprocess.Popen(
                [
                    "/usr/bin/ssh", "-T",
                    "-o", "StrictHostKeyChecking=accept-new",
                    "-o", "ExitOnForwardFailure=yes",
                    "-o", "ServerAliveInterval=30",
                    "-R", f"80:127.0.0.1:{self.port}",
                    "nokey@localhost.run",
                ],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                stdin=subprocess.DEVNULL,
            )
            url = self._read_until(r"https://[a-z0-9]+\.lhr\.life", timeout=90)
            if url:
                self.public_base = url
                self.log.info(f"터널 주소 확보: {url}")
                return True
            self._kill_proc()
        except Exception as e:
            self.log.warning(f"localhost.run 실패: {e}")
            self._kill_proc()
        return False

    def verify(self, url: str, path: Path, tries: int = 8, delay: int = 4) -> bool:
        """Meta가 받아가기 전에 우리가 먼저 확인: URL이 열리고, 내용이 실제 영상과 일치하는지.
        (중간 페이지/오류 페이지가 200으로 오는 경우를 걸러낸다)"""
        with open(path, "rb") as f:
            expected = f.read(1024)
        for _ in range(tries):
            try:
                r = requests.get(
                    url, headers={"Range": "bytes=0-1023"}, timeout=20, stream=True
                )
                if r.status_code in (200, 206):
                    got = next(r.iter_content(1024), b"")
                    r.close()
                    if got[: len(expected)] == expected[: len(got)] and len(got) > 0:
                        return True
                    self.log.warning("터널 응답이 영상 내용과 다릅니다(중간 페이지 의심). 재시도...")
            except Exception:
                pass
            time.sleep(delay)
        return False

    def _kill_proc(self):
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        self.public_base = None

    def stop(self):
        self._kill_proc()
        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                pass
            self.server = None
