from __future__ import annotations

import argparse
import re
import sys
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
if __name__ == "__main__":
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
    try:
        import cv2
    except ImportError as exc:
        raise SystemExit("OpenCV가 필요합니다: sudo apt install python3-opencv") from exc

    source = build_frame_source(config)
    return capture_samples(source, cv2, output_dir, args.class_name, count, interval)


def capture_samples(
    source, cv2, output_dir: Path, class_name: str, count: int, interval: float
) -> int:
    """Own the camera and iterator for the entire capture, including startup."""
    try:
        print(f"저장 위치: {output_dir}")
        print("물체의 각도·거리·배경·조명을 조금씩 바꾸세요. 3초 뒤 시작합니다.")
        time.sleep(3)
        # Close the suspended iterator before closing the device it uses.
        with closing(source.frames(count)) as frames:
            index = 0
            # enumerate's reusable result tuple can keep the previous image.
            for frame in frames:
                index += 1
                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    path = output_dir / f"{class_name}_{timestamp}_{index:04d}.jpg"
                    _save_frame(source.backend_name, cv2, frame, path)
                    print(f"{index:04d}/{count}: {path.name}")
                finally:
                    frame = None
                if index < count:
                    time.sleep(interval)
    except DetectionError as exc:
        print(f"실패: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n사용자가 촬영을 중지했습니다.")
        return 130
    finally:
        source.close()

    print(f"촬영 완료: {output_dir}")
    return 0


def _save_frame(backend: str, cv2, frame, path: Path) -> None:
    frame_to_save = None
    try:
        frame_to_save = (
            cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            if backend == "picamera2"
            else frame
        )
        if not cv2.imwrite(str(path), frame_to_save, [cv2.IMWRITE_JPEG_QUALITY, 92]):
            raise DetectionError(f"사진 저장에 실패했습니다: {path}")
    finally:
        # Even a retained exception traceback must not keep our image references.
        frame_to_save = frame = None


if __name__ == "__main__":
    raise SystemExit(main())
