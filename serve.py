"""Production entrypoint: validate configuration before starting Waitress."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="설정만 확인하고 종료 (DB·카메라 접근 없음)")
    parser.add_argument("--allow-mock", action="store_true", help="웹 확인용 mock 인식 허용 (보안 검사는 유지)")
    args = parser.parse_args(argv)
    if not (ROOT / ".env").is_file():
        print(".env가 없습니다. 기존 설정 파일을 프로젝트 폴더에 준비하세요.", file=sys.stderr)
        return 1
    load_dotenv(ROOT / ".env")
    # Resolve relative DB/model paths identically for manual and systemd runs.
    os.chdir(ROOT)
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(name, "2")

    from equipment_manager import create_app
    from equipment_manager.config import Config
    from equipment_manager.deployment import WAITRESS_OPTIONS, validate_deployment
    from waitress import serve

    try:
        validate_deployment(vars(Config), ROOT, allow_mock=args.allow_mock)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.check:
        print("배포 설정 검사 통과. DB·카메라·모델 추론 및 메모리 안정성은 별도 확인이 필요합니다.")
        return 0
    if Config.DETECTOR_MODE == "mock":
        print("주의: 웹 확인용 mock 인식입니다. 실제 기자재 인식 운영이 아닙니다.", flush=True)
    app = create_app({"DEBUG": False, "TESTING": False})
    try:
        serve(app, **WAITRESS_OPTIONS)
    finally:
        app.extensions["shutdown_services"]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
