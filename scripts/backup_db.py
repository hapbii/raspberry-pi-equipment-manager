from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


root = Path(__file__).resolve().parent.parent
load_dotenv(root / ".env")
sys.path.insert(0, str(root))

from equipment_manager.backup import backup_database  # noqa: E402


configured_source = Path(
    os.getenv("DATABASE", str(root / "instance" / "equipment.db"))
).expanduser()
source = configured_source if configured_source.is_absolute() else root / configured_source
backup_dir = root / "backups"

try:
    destination = backup_database(source, backup_dir)
except (OSError, RuntimeError) as exc:
    raise SystemExit(str(exc)) from exc

print(f"백업 완료: {destination}")
print(f"파일 크기: {destination.stat().st_size / 1024:.1f} KiB")
