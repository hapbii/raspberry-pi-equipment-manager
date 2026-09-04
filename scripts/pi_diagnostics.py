from __future__ import annotations

import platform
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from equipment_manager import create_app  # noqa: E402
from equipment_manager.system_metrics import current_rss_mb  # noqa: E402
from equipment_manager.vision import DetectionError, get_detection_service  # noqa: E402


def linux_memory() -> tuple[float | None, float | None]:
    path = Path("/proc/meminfo")
    if not path.exists():
        return None, None
    values = {}
    for line in path.read_text(encoding="ascii").splitlines():
        key, value = line.split(":", 1)
        values[key] = int(value.strip().split()[0]) / 1024
    return values.get("MemTotal"), values.get("MemAvailable")


def main() -> int:
    app = create_app({"HEARTBEAT_ENABLED": False})
    total_mb, available_mb = linux_memory()
    print("=== Raspberry Pi 실제 장치 사전 점검 ===")
    print(f"OS: {platform.platform()}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"프로세스 RSS: {current_rss_mb()} MB")
    if total_mb is not None:
        print(f"전체 메모리: {total_mb:.1f} MB / 사용 가능: {available_mb:.1f} MB")
    print(f"인식 모드: {app.config['DETECTOR_MODE']}")
    print(f"카메라: {app.config['CAMERA_BACKEND']} {app.config['CAMERA_WIDTH']}x{app.config['CAMERA_HEIGHT']}")
    print(f"모델: {app.config['YOLO_MODEL_PATH']}")
    print(f"입력 크기: {app.config['YOLO_IMAGE_SIZE']}")

    if app.config["DETECTOR_MODE"] != "yolo":
        print("실패: .env의 DETECTOR_MODE를 yolo로 변경하세요.")
        app.extensions["shutdown_services"]()
        return 2

    try:
        with app.app_context():
            result = get_detection_service().preflight()
        print("\n[통과] YOLO 모델 로딩")
        print(f"[통과] 카메라 프레임: {result.frame_width}x{result.frame_height}")
        if result.detected_label:
            print(f"[통과] 현재 물체: {result.detected_label} ({result.confidence:.1%})")
        else:
            print("[안내] 현재 프레임에서 물체는 검출되지 않았지만 카메라와 모델 실행은 정상입니다.")
        print(f"전체 사전 점검 시간: {result.duration_ms / 1000:.2f}초")
        print(f"점검 후 RSS: {result.memory_rss_mb} MB")
        return 0
    except DetectionError as exc:
        print(f"\n[실패] {exc}")
        return 1
    finally:
        app.extensions["shutdown_services"]()


if __name__ == "__main__":
    raise SystemExit(main())
