from __future__ import annotations

import logging
from copy import copy
from logging.handlers import RotatingFileHandler
from pathlib import Path


class BoundedErrorHandler(RotatingFileHandler):
    """Limit even a single oversized exception and never reopen after close."""

    record_limit = 16 * 1024

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        size = self.stream.tell()
        # Korean text is multibyte; character counts do not bound disk usage.
        # Reserve two bytes per newline for Windows text-mode translation.
        text = self.format(record) + self.terminator
        write_size = len(text.encode("utf-8", errors="replace")) + text.count("\n")
        return size > 0 and size + write_size >= self.maxBytes

    def emit(self, record: logging.LogRecord) -> None:
        # Handler.handle holds the same lock used by clear/close.
        if self._closed:
            return
        try:
            text = self.format(record)
            encoded = text.encode("utf-8", errors="replace")
            if len(encoded) > self.record_limit:
                suffix = b"\n[log entry truncated]"
                text = encoded[: self.record_limit - len(suffix)].decode(
                    "utf-8", errors="ignore"
                ) + suffix.decode("ascii")
            bounded = copy(record)
            bounded.msg, bounded.args = text, ()
            bounded._bounded_error_text = True
            bounded.exc_info = bounded.exc_text = bounded.stack_info = None
            # Parent rollover and write now format the already bounded string.
            super().emit(bounded)
        except Exception:
            self.handleError(record)

    def format(self, record: logging.LogRecord) -> str:
        # The timestamp is rendered by the formatter only for the original record.
        if getattr(record, "_bounded_error_text", False):
            return str(record.msg)
        return super().format(record)


class ErrorLogStore:
    """Bounded file storage for error-level application logs."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_bytes: int,
        backup_count: int,
        display_bytes: int,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_count = min(5, max(1, backup_count))
        self.display_bytes = min(256 * 1024, max(1024, display_bytes))
        self._logger = logging.getLogger("equipment_manager")
        self._handler = BoundedErrorHandler(
            self.path,
            maxBytes=max(64 * 1024, max_bytes),
            backupCount=self.backup_count,
            encoding="utf-8",
            delay=True,
        )
        self._handler.setLevel(logging.ERROR)
        self._handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        self._logger.addHandler(self._handler)
        self._closed = False

    def snapshot(self) -> dict[str, object]:
        """Return a bounded tail of the current log and disk usage metadata."""
        self._handler.acquire()
        try:
            if self._handler.stream is not None:
                self._handler.flush()

            paths = self._log_paths()
            existing = [path for path in paths if path.is_file()]
            total_size = sum(path.stat().st_size for path in existing)
            text, truncated = self._read_recent_text(existing)
            return {
                "text": text,
                "has_logs": bool(text.strip()),
                "truncated": truncated,
                "total_size_bytes": total_size,
                "file_count": len(existing),
                "path": str(self.path),
            }
        finally:
            self._handler.release()

    def clear(self) -> None:
        """Remove the active log and every rotated backup safely."""
        self._handler.acquire()
        try:
            if self._handler.stream is not None:
                self._handler.flush()
                self._handler.stream.close()
                self._handler.stream = None
            for path in self._log_paths():
                path.unlink(missing_ok=True)
        finally:
            self._handler.release()

    def close(self) -> None:
        self._handler.acquire()
        try:
            if self._closed:
                return
            self._closed = True
            self._logger.removeHandler(self._handler)
            self._handler.close()
        finally:
            self._handler.release()

    def _log_paths(self) -> list[Path]:
        return [self.path] + [
            Path(f"{self.path}.{index}")
            for index in range(1, self.backup_count + 1)
        ]

    def _read_recent_text(self, existing: list[Path]) -> tuple[str, bool]:
        if not existing:
            return "", False

        chunks: list[bytes] = []
        remaining = self.display_bytes
        truncated = False

        # The active file is newest, followed by .1, .2 and so on.
        for path in existing:
            size = path.stat().st_size
            if size <= 0:
                continue
            read_size = min(size, remaining)
            with path.open("rb") as log_file:
                log_file.seek(-read_size, 2)
                chunk = log_file.read(read_size)
            chunks.insert(0, chunk)
            remaining -= read_size
            if read_size < size:
                truncated = True
                break
            if remaining <= 0:
                truncated = len(existing) > len(chunks)
                break

        raw = b"".join(chunks)
        if truncated:
            first_newline = raw.find(b"\n")
            if first_newline >= 0:
                raw = raw[first_newline + 1 :]
        return raw.decode("utf-8", errors="replace").strip(), truncated


def get_error_log_store() -> ErrorLogStore:
    from flask import current_app

    return current_app.extensions["error_log_store"]
