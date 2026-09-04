from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="YOLO 모델을 사진 한 장으로 시험합니다.")
    parser.add_argument("model", type=Path, help="best.pt 또는 NCNN 모델 폴더")
    parser.add_argument("image", type=Path, help="시험할 이미지")
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--conf", type=float, default=0.60)
    args = parser.parse_args()

    if not args.model.exists():
        raise SystemExit(f"모델을 찾을 수 없습니다: {args.model}")
    if not args.image.exists():
        raise SystemExit(f"이미지를 찾을 수 없습니다: {args.image}")

    from ultralytics import YOLO

    model = YOLO(str(args.model))
    result = model.predict(
        source=str(args.image),
        imgsz=args.imgsz,
        conf=args.conf,
        save=True,
        project="runs",
        name="single-image-test",
        exist_ok=True,
        verbose=False,
    )[0]

    if result.boxes is None or len(result.boxes) == 0:
        print("인식 결과 없음")
        return
    for class_id, confidence in zip(result.boxes.cls.tolist(), result.boxes.conf.tolist()):
        print(f"{result.names[int(class_id)]}: {confidence:.3f}")
    print("표시된 결과 이미지는 runs/single-image-test에 저장되었습니다.")


if __name__ == "__main__":
    main()
