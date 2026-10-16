"""Persist developer-selected recognition mode without rewriting other settings."""
from __future__ import annotations

import io
import os
from pathlib import Path
import tempfile

from dotenv import dotenv_values, set_key
from flask import current_app

from .vision import get_detection_service


class ModeChangeError(ValueError):
    pass


def _save_mode(path: Path, mode: str, expected: str) -> None:
    # Stage both keys privately and replace once. A failed write cannot leave
    # DETECTOR_MODE changed without the explicit preview startup opt-in.
    if path.is_symlink():
        raise ModeChangeError(".env가 링크 파일입니다. 일반 설정 파일로 준비해 주세요.")
    original = path.read_bytes()
    values = dotenv_values(stream=io.StringIO(original.decode("utf-8-sig")), interpolate=False)
    saved = (values.get("DETECTOR_MODE") or "mock").strip().lower()
    if saved != expected:
        raise ModeChangeError(".env 설정이 실행 중인 모드와 다릅니다. 서버를 다시 시작한 뒤 변경해 주세요.")
    descriptor, name = tempfile.mkstemp(prefix=".env-mode-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(original)
        set_key(temporary, "DETECTOR_MODE", mode, quote_mode="never")
        set_key(temporary, "ALLOW_MOCK_MODE", "true" if mode == "mock" else "false", quote_mode="never")
        os.chmod(temporary, 0o600)
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        if path.read_bytes() != original:
            raise ModeChangeError("설정 파일이 변경되었습니다. 새로고침 후 다시 시도해 주세요.")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def switch_detector_mode(mode: str, expected: str) -> bool:
    if mode not in {"yolo", "mock"} or expected not in {"yolo", "mock"}:
        raise ModeChangeError("YOLO 또는 mock 모드를 선택해 주세요.")
    config = current_app.config
    if mode == "yolo":
        model = Path(config["YOLO_MODEL_PATH"]).expanduser()
        if not model.is_absolute():
            model = Path(current_app.root_path).parent / model
        if not model.exists() or not os.access(model, os.R_OK):
            raise ModeChangeError("YOLO 모델을 읽을 수 없습니다. 모델 경로와 파일 권한을 확인해 주세요.")
    return get_detection_service().switch_mode(
        config, mode, expected,
        lambda: _save_mode(Path(config["ENV_FILE_PATH"]), mode, expected),
    )
