"""Photo codec facade. Native image libraries load only in a limited child."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import threading
import time

MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_DECODER_OUTPUT = MAX_PHOTO_BYTES + 4096  # Image plus bounded JSON header.
DECODE_TIMEOUT = 15
logger = logging.getLogger(__name__)
FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP", "image/heic": "HEIF", "image/heif": "HEIF"}


class InvalidPhotoError(ValueError):
    def __init__(self, message: str, *, reason="invalid_photo", exit_code=None):
        super().__init__(message)
        self.reason, self.exit_code = reason, exit_code


@dataclass(frozen=True)
class SanitizedPhoto:
    content: bytes
    width: int
    height: int
    mime_type: str
    had_metadata: bool
    resized: bool
    decode_limits: dict


def sanitized_photo_path(path: str) -> str:
    if not path.startswith(("avatars/", "ride-media/")) or ".." in path.split("/"):
        raise InvalidPhotoError("Invalid photo storage path")
    return f"sanitized/{path}"


def strip_photo_metadata(content: bytes, mime_type: str) -> SanitizedPhoto:
    if not content or len(content) > MAX_PHOTO_BYTES or mime_type not in FORMATS:
        raise InvalidPhotoError("Invalid photo size or format")
    process = None
    rejection = []
    try:
        with tempfile.TemporaryDirectory(prefix="photo-decode-") as directory:
            process = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).with_name("photo_decode_worker.py")), mime_type],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd=directory, env={}, close_fds=True, start_new_session=True,
            )
            stop = threading.Event()
            monitor = None
            if sys.platform == "darwin":
                monitor = threading.Thread(target=_limit_rss, args=(process, stop, rejection), daemon=True)
                monitor.start()
            try:
                output = _capture_decoder(process, content)
                if process.returncode:
                    raise InvalidPhotoError("Decoder failed", reason=rejection[0] if rejection else "decode_failed")
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                stop.set()
                if monitor:
                    monitor.join(timeout=2)
                for pipe in (process.stdin, process.stdout):
                    if pipe and not pipe.closed:
                        pipe.close()
        header, clean = output.split(b"\n", 1)
        info = json.loads(header)
        if not 0 < len(clean) <= MAX_PHOTO_BYTES or not all(0 < info[k] <= 4096 for k in ("width", "height")):
            raise ValueError("Invalid decoder result")
        if info["mime_type"] not in ("image/jpeg", "image/png", "image/webp"):
            raise ValueError("Invalid decoder format")
        return SanitizedPhoto(content=clean, **info)
    except Exception as exc:
        reason = (exc.reason if isinstance(exc, InvalidPhotoError) else
                  "wall_timeout" if isinstance(exc, subprocess.TimeoutExpired) else "invalid_decoder_result")
        exit_code = process.returncode if process is not None else None
        logger.warning("Photo decode rejected reason=%s exit_code=%s", reason, exit_code)
        raise InvalidPhotoError("Invalid photo or decoder resource limit exceeded",
                                reason=reason, exit_code=exit_code) from exc


def _capture_decoder(process: subprocess.Popen, content: bytes) -> bytes:
    """Drain both pipes without communicate()'s unbounded stdout allocation."""
    deadline = time.monotonic() + DECODE_TIMEOUT
    output = bytearray()
    pending = memoryview(content)
    with selectors.DefaultSelector() as selector:
        for pipe, event in ((process.stdin, selectors.EVENT_WRITE), (process.stdout, selectors.EVENT_READ)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, event)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("photo decoder", DECODE_TIMEOUT)
            for key, _ in selector.select(remaining):
                if key.fileobj is process.stdin:
                    try:
                        pending = pending[os.write(key.fd, pending[:65536]):]
                    except BrokenPipeError:
                        pending = memoryview(b"")
                    if not pending:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                else:
                    chunk = os.read(key.fd, min(65536, MAX_DECODER_OUTPUT + 1 - len(output)))
                    output.extend(chunk)
                    if len(output) > MAX_DECODER_OUTPUT:
                        raise InvalidPhotoError("Decoder output exceeded limit", reason="output_limit")
                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
        process.wait(timeout=max(.001, deadline - time.monotonic()))
    return bytes(output)


def _limit_rss(process: subprocess.Popen, stop: threading.Event, rejection: list) -> None:
    """macOS fallback: monitor outside the decoder, even while native code holds its GIL."""
    while not stop.wait(.05) and process.poll() is None:
        try:
            result = subprocess.run(["/bin/ps", "-o", "rss=", "-p", str(process.pid)],
                                    capture_output=True, env={}, close_fds=True, timeout=1, check=True)
            if int(result.stdout.strip()) * 1024 > 1024**3:
                rejection.append("memory_limit")
                process.kill()
                return
        except Exception:
            if process.poll() is None:
                rejection.append("memory_monitor_failed")
                process.kill()  # Cannot measure safely: fail closed.
            return
