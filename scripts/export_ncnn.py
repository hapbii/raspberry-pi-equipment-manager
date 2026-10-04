"""Export a copy of a trained model; preserve the original checkpoint."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="best.pt 원본을 보존하며 NCNN 모델을 추가 생성")
    parser.add_argument("model", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, default=320)
    args = parser.parse_args()
    source = args.model.resolve()
    destination = args.output_dir.resolve()
    if not source.is_file() or source.suffix != ".pt":
        parser.error("읽을 수 있는 .pt 모델 파일이 필요합니다.")
    if args.imgsz < 160 or args.imgsz % 32:
        parser.error("imgsz는 160 이상이며 32의 배수여야 합니다.")
    destination.mkdir(parents=True, exist_ok=True)
    copied = destination / "best.pt"
    exported = destination / "best_ncnn_model"
    if copied == source or copied.exists() or exported.exists():
        parser.error("원본과 다른 비어 있는 출력 폴더를 지정하세요.")
    original_hash = sha256(source)
    shutil.copy2(source, copied)
    config_dir = destination / 'ultralytics-settings'
    config_dir.mkdir(exist_ok=True)
    os.environ['YOLO_CONFIG_DIR'] = str(config_dir)
    from ultralytics import YOLO, __version__

    # TorchScript/PNNX on Windows can fail with Korean paths. Export in a temporary
    # ASCII directory and then copy the finished model into the chosen workspace.
    with tempfile.TemporaryDirectory(prefix="equipment-ncnn-") as staging_name:
        staging = Path(staging_name).resolve()
        assert staging.is_relative_to(Path(tempfile.gettempdir()).resolve())
        staged_model = staging / "best.pt"
        shutil.copy2(copied, staged_model)
        model = YOLO(str(staged_model))
        names = dict(model.names)
        result = Path(model.export(format="ncnn", imgsz=args.imgsz, batch=1, device="cpu", quantize=32))
        assert result.is_dir() and result.resolve().is_relative_to(staging)
        shutil.copytree(result, exported)
    assert sha256(source) == original_hash == sha256(copied)
    assert list(YOLO(str(exported), task="detect").names.values()) == list(names.values())
    files = {str(p.relative_to(destination)): {"bytes": p.stat().st_size, "sha256": sha256(p)}
             for p in exported.rglob("*") if p.is_file()}
    report = {"source": str(source), "source_sha256": original_hash, "original_unchanged": True,
              "ultralytics": __version__, "imgsz": args.imgsz, "weight_precision": "FP32",
              "classes": names, "pt": "best.pt", "ncnn": "best_ncnn_model", "files": files}
    (destination / "export_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("EXPORT_VERIFIED", exported)


if __name__ == "__main__":
    main()
