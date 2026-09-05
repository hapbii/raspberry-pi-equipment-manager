from __future__ import annotations

import os
import secrets
from pathlib import Path


ACCOUNT_KEYS = (
    "DEVELOPER_USERNAME",
    "DEVELOPER_PASSWORD",
    "TEACHER_USERNAME",
    "TEACHER_PASSWORD",
    "STATION_AUTH_REQUIRED",
)


def _read_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def ensure_role_accounts(env_path: Path) -> tuple[dict[str, str], list[str]]:
    env_path = env_path.expanduser().resolve()
    if not env_path.is_file():
        raise FileNotFoundError(f".env 파일을 찾을 수 없습니다: {env_path}")

    original = env_path.read_text(encoding="utf-8")
    current = _read_values(original)
    legacy_password = current.get("ADMIN_PASSWORD", "")
    if not legacy_password or legacy_password == "admin1234":
        legacy_password = secrets.token_urlsafe(12)

    desired = {
        "DEVELOPER_USERNAME": current.get("DEVELOPER_USERNAME", "developer"),
        "DEVELOPER_PASSWORD": current.get("DEVELOPER_PASSWORD", legacy_password),
        "TEACHER_USERNAME": current.get("TEACHER_USERNAME", "teacher"),
        "TEACHER_PASSWORD": current.get(
            "TEACHER_PASSWORD", secrets.token_urlsafe(12)
        ),
        "STATION_AUTH_REQUIRED": current.get("STATION_AUTH_REQUIRED", "false"),
    }
    missing = [key for key in ACCOUNT_KEYS if key not in current]
    if missing:
        separator = "" if original.endswith("\n") else "\n"
        additions = ["", "# 역할별 관리자 계정"]
        additions.extend(f"{key}={desired[key]}" for key in missing)
        updated = original + separator + "\n".join(additions) + "\n"
        temporary = env_path.with_name(f"{env_path.name}.{secrets.token_hex(4)}.tmp")
        try:
            temporary.write_text(updated, encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(env_path)
        finally:
            temporary.unlink(missing_ok=True)

    return desired, missing
