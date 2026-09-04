from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path


root = Path(__file__).resolve().parent.parent
source = Path(os.getenv("DATABASE", str(root / "instance" / "equipment.db"))).expanduser()
backup_dir = root / "backups"

if not source.exists():
    raise SystemExit(f"DB 파일을 찾을 수 없습니다: {source}")

backup_dir.mkdir(parents=True, exist_ok=True)
destination = backup_dir / f"equipment-{datetime.now():%Y%m%d-%H%M%S}.db"

with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
    src.backup(dst)

print(destination)
