"""Read the root-owned updater's last result without launching a process."""
import json
from pathlib import Path


UPDATE_STATUS = Path("/var/lib/equipment-manager-update/status.json")


def update_status():
    try:
        with UPDATE_STATUS.open(encoding="utf-8") as stream:
            data = json.loads(stream.read(8192))
        if not isinstance(data, dict) or data.get("state") not in {"running", "success", "failed"}:
            return None
        return {key: str(data.get(key, "")) for key in (
            "state", "message", "started_at", "finished_at", "before", "after",
        )}
    except (OSError, ValueError):
        return None
