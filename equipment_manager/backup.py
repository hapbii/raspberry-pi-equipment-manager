from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path


def backup_database(source: Path, backup_dir: Path) -> Path:
    source = source.expanduser().resolve()
    backup_dir = backup_dir.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"DB 파일을 찾을 수 없습니다: {source}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"equipment-{datetime.now():%Y%m%d-%H%M%S-%f}.db"

    try:
        with closing(sqlite3.connect(source)) as src, closing(
            sqlite3.connect(destination)
        ) as dst:
            src.execute("PRAGMA busy_timeout = 5000")
            src.backup(dst)
            integrity = dst.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"백업 무결성 검사에 실패했습니다: {integrity}")
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return destination
