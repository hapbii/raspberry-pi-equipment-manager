from __future__ import annotations

import json
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_json(name: str, default: dict) -> dict:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return default
    return value if isinstance(value, dict) else default


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-before-school-use")
    DATABASE = os.getenv("DATABASE", str(BASE_DIR / "instance" / "equipment.db"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin1234")
    STATION_AUTH_REQUIRED = env_bool("STATION_AUTH_REQUIRED", False)
    STATION_PIN = os.getenv("STATION_PIN", "1234")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
    CSRF_ENABLED = env_bool("CSRF_ENABLED", True)

    DEFAULT_EQUIPMENT = [
        item.strip()
        for item in os.getenv("DEFAULT_EQUIPMENT", "멀티미터,아두이노,브레드보드").split(",")
        if item.strip()
    ]
    DEFAULT_QUANTITY = env_int("DEFAULT_QUANTITY", 10)

    DETECTOR_MODE = os.getenv("DETECTOR_MODE", "mock").lower()
    YOLO_MODEL_PATH = os.getenv("YOLO_MODEL_PATH", str(BASE_DIR / "models" / "best.pt"))
    YOLO_IMAGE_SIZE = env_int("YOLO_IMAGE_SIZE", 320)
    YOLO_CONFIDENCE = env_float("YOLO_CONFIDENCE", 0.60)
    YOLO_MIN_VOTES = env_int("YOLO_MIN_VOTES", 3)
    YOLO_FRAME_COUNT = env_int("YOLO_FRAME_COUNT", 5)
    YOLO_MAX_DETECTIONS = env_int("YOLO_MAX_DETECTIONS", 5)
    YOLO_CLASS_ALIASES = env_json("YOLO_CLASS_ALIASES", {})
    INFERENCE_THREADS = env_int("INFERENCE_THREADS", 2)
    GC_INTERVAL_SCANS = env_int("GC_INTERVAL_SCANS", 20)

    CAMERA_BACKEND = os.getenv("CAMERA_BACKEND", "picamera2").lower()
    CAMERA_INDEX = env_int("CAMERA_INDEX", 0)
    CAMERA_WIDTH = env_int("CAMERA_WIDTH", 640)
    CAMERA_HEIGHT = env_int("CAMERA_HEIGHT", 480)
    CAMERA_BUFFER_COUNT = env_int("CAMERA_BUFFER_COUNT", 2)
    CAMERA_WARMUP_SECONDS = env_float("CAMERA_WARMUP_SECONDS", 0.5)

    GPIO_ENABLED = env_bool("GPIO_ENABLED", False)
    GPIO_GREEN_PIN = env_int("GPIO_GREEN_PIN", 17)
    GPIO_RED_PIN = env_int("GPIO_RED_PIN", 27)
    GPIO_BUZZER_PIN = env_int("GPIO_BUZZER_PIN", 22)

    SCAN_TOKEN_TTL_SECONDS = env_int("SCAN_TOKEN_TTL_SECONDS", 90)
    DUPLICATE_WINDOW_SECONDS = env_int("DUPLICATE_WINDOW_SECONDS", 5)
    HEARTBEAT_ENABLED = env_bool("HEARTBEAT_ENABLED", True)
    HEARTBEAT_INTERVAL_SECONDS = env_int("HEARTBEAT_INTERVAL_SECONDS", 15)
    DEVICE_OFFLINE_SECONDS = env_int("DEVICE_OFFLINE_SECONDS", 45)
    DEVICE_NAME = os.getenv("DEVICE_NAME", "기자재 인식 스테이션")
    MEMORY_WARNING_MB = env_int("MEMORY_WARNING_MB", 1200)
    MAX_CONTENT_LENGTH = env_int("MAX_CONTENT_LENGTH", 1_000_000)
