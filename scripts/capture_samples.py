from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from equipment_manager.config import Config  # noqa: E402
from equipment_manager.vision.camera import build_frame_source  # noqa: E402
from equipment_manager.vision.types import DetectionError  # noqa: E402


def safe_class_name(value: str) -> str:
    name = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", value.strip())
    if not name:
        raise argparse.ArgumentTypeError("기자재 이름에 사용할 수 있는 문자가 없습니다.")
    return name


def main() -> int:
    parser = argparse.ArgumentParser(description="라즈베리파이 카메라로 YOLO 학습 사진 수집")
    parser.add_argument("class_name", type=safe_class_name, help="예: multimeter")
    parser.add_argument("--count", type=int, default=200, help="촬영 장수")
    parser.add_argument("--interval", type=float, default=0.5, help="사진 사이 대기 시간(초)")
    parser.add_argument("--output", type=Path, default=ROOT / "datasets" / "raw")
    args = parser.parse_args()

    count = max(1, args.count)
    interval = max(0.0, args.interval)
    output_dir = args.output.expanduser().resolve() / args.class_name
    output_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "CAMERA_BACKEND": Config.CAMERA_BACKEND,
        "CAMERA_INDEX": Config.CAMERA_INDEX,
        "CAMERA_WIDTH": Config.CAMERA_WIDTH,
        "CAMERA_HEIGHT": Config.CAMERA_HEIGHT,
        "CAMERA_BUFFER_COUNT": Config.CAMERA_BUFFER_COUNT,
        "CAMERA_WARMUP_SECONDS": Config.CAMERA_WARMUP_SECONDS,
    }
    source = build_frame_source(config)

    try:
        import cv2
    except ImportError as exc:
        raise SystemExit("OpenCV가 필요합니다: sudo apt install python3-opencv") from exc

    print(f"저장 위치: {output_dir}")
    print("물체의 각도·거리·배경·조명을 조금씩 바꾸세요. 3초 뒤 시작합니다.")
    time.sleep(3)

    try:
        for index, frame in enumerate(source.frames(count), start=1):
            if source.backend_name == "picamera2":
                frame_to_save = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            else:
                frame_to_save = frame
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = output_dir / f"{args.class_name}_{timestamp}_{index:04d}.jpg"
            if not cv2.imwrite(str(path), frame_to_save, [cv2.IMWRITE_JPEG_QUALITY, 92]):
                raise DetectionError(f"사진 저장에 실패했습니다: {path}")
            print(f"{index:04d}/{count}: {path.name}")
            del frame_to_save, frame
            if index < count:
                time.sleep(interval)
    except DetectionError as exc:
        print(f"실패: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n사용자가 촬영을 중지했습니다.")
    finally:
        source.close()

    print(f"촬영 완료: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
