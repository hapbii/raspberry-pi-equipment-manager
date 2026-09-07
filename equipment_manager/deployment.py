"""Read-only deployment checks and bounded settings for the 2GB Pi."""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


WAITRESS_OPTIONS = {
    "host": "0.0.0.0",
    "port": 8080,
    "threads": 2,
    "connection_limit": 32,
    "backlog": 64,
    "channel_timeout": 60,
    "cleanup_interval": 10,
    "max_request_header_size": 16 * 1024,
    "max_request_body_size": 1_000_000,
    "inbuf_overflow": 64 * 1024,
    "outbuf_overflow": 256 * 1024,
    "outbuf_high_watermark": 1024 * 1024,
    "expose_tracebacks": False,
}


def validate_deployment(config: Mapping, root: Path, *, allow_mock: bool = False) -> None:
    """Fail before opening a DB/camera; report field names, never secret values."""
    errors = []
    secret = str(config.get("SECRET_KEY") or "")
    if len(secret) < 32 or secret in {"dev-secret-change-before-school-use", "change-me"}:
        errors.append("SECRET_KEY: 예제 값이 아닌 무작위 32자 이상 값을 설정하세요.")
    for role in ("DEVELOPER", "TEACHER"):
        username = str(config.get(f"{role}_USERNAME") or "")
        password = str(config.get(f"{role}_PASSWORD") or "")
        if not username.strip() or username != username.strip():
            errors.append(f"{role}_USERNAME: 비어 있지 않고 앞뒤 공백 없는 아이디가 필요합니다.")
        if len(password) < 12 or password in {"admin1234", "developer1234", "teacher1234"}:
            errors.append(f"{role}_PASSWORD: 예제 값이 아닌 12자 이상 비밀번호가 필요합니다.")
    if config.get("DEVELOPER_USERNAME") == config.get("TEACHER_USERNAME"):
        errors.append("DEVELOPER_USERNAME / TEACHER_USERNAME: 서로 다른 아이디를 사용하세요.")
    if not config.get("CSRF_ENABLED", True):
        errors.append("CSRF_ENABLED: 배포 시 true가 필요합니다.")
    if config.get("DEBUG") or config.get("TESTING"):
        errors.append("DEBUG / TESTING: 배포 시 false가 필요합니다.")
    if not config.get("STATION_AUTH_REQUIRED", True):
        errors.append("STATION_AUTH_REQUIRED: 교내 배포 시 true가 필요합니다.")
    pin = str(config.get("STATION_PIN") or "")
    if not (6 <= len(pin) <= 12 and pin.isascii() and pin.isdigit()) or len(set(pin)) == 1:
        errors.append("STATION_PIN: 같은 숫자 반복을 피한 6~12자리 숫자가 필요합니다.")
    mode = config.get("DETECTOR_MODE")
    if mode == "mock":
        if not allow_mock:
            errors.append("DETECTOR_MODE: 실제 운영은 yolo가 필요합니다. 웹 확인만 할 때는 --allow-mock을 사용하세요.")
    elif mode == "yolo":
        raw_model = config.get("YOLO_MODEL_PATH")
        model = Path(raw_model or "models/best.pt")
        if not model.is_absolute():
            model = root / model
        if not raw_model or not model.exists() or not os.access(model, os.R_OK):
            errors.append("YOLO_MODEL_PATH: 읽을 수 있는 모델 파일 또는 NCNN 폴더가 필요합니다.")
    else:
        errors.append("DETECTOR_MODE: yolo 또는 mock을 설정하세요.")
    if errors:
        raise ValueError("배포 설정을 확인하세요 (.env는 변경하지 않았습니다):\n- " + "\n- ".join(errors))
