from __future__ import annotations

import argparse
import math
import re
import sys
import time
import uuid
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
    if not name or len(name) > 60:
        raise argparse.ArgumentTypeError("기자재 이름에 사용할 수 있는 문자가 없습니다.")
    return name


def main() -> int:
    parser = argparse.ArgumentParser(description="라즈베리파이 카메라로 YOLO 학습 사진 수집")
    parser.add_argument("class_name", type=safe_class_name, help="예: multimeter")
    parser.add_argument("--count", type=int, default=200, help="촬영 장수")
    parser.add_argument("--interval", type=float, default=0.5, help="사진 사이 대기 시간(초)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--manual", action="store_true", help="엔터로 한 장씩 촬영, q로 종료 (SSH 가능)")
    mode.add_argument("--preview", action="store_true", help="PC 브라우저에서 실시간 화면을 보며 버튼으로 촬영 (SSH 터널)")
    parser.add_argument("--preview-port", type=int, default=8081, help="미리보기 포트 (기본 8081)")
    parser.add_argument("--delay", type=float, default=1.0, help="수동 촬영에서 엔터 후 대기 시간(초)")
    parser.add_argument("--backend", choices=("picamera2", "opencv", "usb"), help="이번 촬영에만 카메라 방식 지정")
    parser.add_argument("--camera-index", type=int, help="USB 카메라 번호 (보통 0)")
    parser.add_argument("--output", type=Path, default=ROOT / "datasets" / "raw")
    args = parser.parse_args()

    if args.count < 1 or any(not math.isfinite(v) or v < 0 for v in (args.interval, args.delay)):
        parser.error("촬영 장수는 1 이상, 대기 시간은 유한한 0 이상의 숫자로 입력하세요.")
    if args.camera_index is not None and args.camera_index < 0:
        parser.error("USB 카메라 번호는 0 이상이어야 합니다.")
    if not 1024 <= args.preview_port <= 65535:
        parser.error("미리보기 포트는 1024~65535 범위여야 합니다.")
    count, interval = args.count, args.interval
    # Separate sessions prevent overwrites and allow train/val splits by shoot.
    session_name = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    output_dir = args.output.expanduser().resolve() / args.class_name / session_name
    output_dir.mkdir(parents=True, exist_ok=False)

    config = {
        "CAMERA_BACKEND": args.backend or Config.CAMERA_BACKEND,
        "CAMERA_INDEX": args.camera_index if args.camera_index is not None else Config.CAMERA_INDEX,
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
    if args.preview:
        from scripts.capture_preview import run_preview

        def save_preview_photo(frame, index):
            try:
                return _save_numbered_frame(source, cv2, frame, output_dir, args.class_name, index, count)
            finally:
                frame = None

        return run_preview(source, cv2, save_preview_photo, args.class_name, count, output_dir, args.preview_port)
    if args.manual:
        return capture_manual(source, cv2, output_dir, args.class_name, count, args.delay)
    return capture_samples(source, cv2, output_dir, args.class_name, count, interval)


def capture_manual(source, cv2, output_dir: Path, class_name: str, count: int, delay: float) -> int:
    """Headless capture: no GUI, extra worker, or image held while waiting for input."""
    saved = 0
    try:
        print(f"저장 위치: {output_dir}")
        print("엔터: 한 장 촬영 / q: 종료. 촬영 전 물체의 각도·거리·조명을 바꾸세요.")
        while saved < count:
            try:
                answer = input(f"[{saved}/{count}] 촬영하려면 엔터 > ").strip().lower()
            except EOFError:
                break
            if answer == "q":
                break
            if answer:
                print("엔터 또는 q만 입력해 주세요.")
                continue
            time.sleep(delay)
            # Discard several queued USB frames after a long keyboard pause.
            frame_count = 4 if source.backend_name == "opencv" else 1
            with closing(source.frames(frame_count)) as frames:
                index = 0
                for frame in frames:
                    try:
                        index += 1
                        if index == frame_count:
                            _save_numbered_frame(source, cv2, frame, output_dir, class_name, saved + 1, count)
                            saved += 1
                    finally:
                        frame = None
                if index != frame_count:
                    raise DetectionError("카메라에서 촬영 프레임을 받지 못했습니다.")
    except (DetectionError, OSError) as exc:
        print(f"실패: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n촬영 중지. 이미 저장한 사진은 유지됩니다.")
        return 130
    finally:
        source.close()
    print(f"촬영 완료: {saved}장 · {output_dir}")
    return 0


def _save_numbered_frame(source, cv2, frame, output_dir, class_name, index, count):
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = output_dir / f"{class_name}_{timestamp}_{index:04d}.jpg"
        _save_frame(source.backend_name, cv2, frame, path)
        print(f"{index:04d}/{count}: {path.name}")
        return path
    finally:
        frame = None


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
                    _save_numbered_frame(source, cv2, frame, output_dir, class_name, index, count)
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
    try:
        # Picamera2 RGB888 arrays and OpenCV frames are BOTH BGR in memory.
        # Swapping channels here would make training photos differ from inference.
        if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92]):
            raise DetectionError(f"사진 저장에 실패했습니다: {path}")
    finally:
        # Even a retained exception traceback must not keep our image references.
        frame = None


if __name__ == "__main__":
    raise SystemExit(main())
