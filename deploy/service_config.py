"""Validate installation as the service user and render a secret-free unit."""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import dotenv_values


def render_service(app_dir: Path, user: str, group: str, *, allow_mock: bool = False) -> str:
    app_dir = app_dir.resolve()
    for name in (user, group):
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_.-]*\$?", name) or name == "root":
            raise ValueError("일반 사용자와 그룹으로 설치해 주세요.")
    # Spaces, &, $, and % are supported; reject ambiguous unit syntax.
    if any(char in app_dir.as_posix() for char in '\n\r\t\\"'):
        raise ValueError("프로젝트 경로에 줄바꿈, 탭, 역슬래시, 큰따옴표를 사용할 수 없습니다.")
    env_path = app_dir / ".env"
    if not env_path.is_file():
        raise ValueError(".env가 없습니다. 먼저 python scripts/create_env.py 를 실행하세요.")
    with env_path.open(encoding="utf-8") as stream:
        values = dotenv_values(stream=stream)
    python = app_dir / ".venv" / "bin" / "python"
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError(".venv/bin/python이 없습니다. 프로젝트의 가상환경을 먼저 준비하세요.")
    if not (app_dir / "wsgi.py").is_file():
        raise ValueError("프로젝트에서 wsgi.py를 찾을 수 없습니다.")
    if not (app_dir / "serve.py").is_file():
        raise ValueError("프로젝트에서 serve.py를 찾을 수 없습니다. 최신 코드를 받아 주세요.")
    mode = (values.get("DETECTOR_MODE", "mock") or "").lower()
    if mode == "mock":
        if not allow_mock:
            raise ValueError("모델 없이 웹 확인용으로 설치하려면 --allow-mock 옵션을 붙이세요. 실제 운영은 DETECTOR_MODE=yolo로 설정하세요.")
    elif mode == "yolo":
        model = Path(values.get("YOLO_MODEL_PATH") or "models/best.pt")
        if not model.is_absolute():
            model = app_dir / model
        if not model.exists() or not os.access(model, os.R_OK):
            raise ValueError("YOLO 모델을 읽을 수 없습니다. .env의 YOLO_MODEL_PATH와 파일 권한을 확인하세요.")
    else:
        raise ValueError("DETECTOR_MODE는 mock 또는 yolo로 설정하세요.")

    template = (Path(__file__).parent / "equipment-manager.service").read_text(encoding="utf-8")
    replacements = {
        "__USER__": user,
        "__GROUP__": group,
        "__APP_DIR__": app_dir.as_posix().replace("%", "%%"),
        "__PYTHON__": '"' + python.as_posix().replace("%", "%%") + '"',
        "__SERVER__": '"' + (app_dir / "serve.py").as_posix().replace("%", "%%") + '"',
        "__MODE_ARGS__": "--allow-mock" if mode == "mock" and allow_mock else "",
    }
    return re.sub(r"__(?:USER|GROUP|APP_DIR|PYTHON|SERVER|MODE_ARGS)__", lambda match: replacements[match[0]], template)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", required=True, type=Path)
    parser.add_argument("--user", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--allow-mock", action="store_true")
    args = parser.parse_args()
    try:
        import waitress  # noqa: F401
    except ImportError:
        print("가상환경에 waitress가 없습니다. 가상환경에서 requirements.txt를 설치하세요.", file=sys.stderr)
        return 1
    unit = render_service(args.app_dir, args.user, args.group, allow_mock=args.allow_mock)
    sys.stdout.write(unit)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"설치 준비 실패: {exc}", file=sys.stderr)
        raise SystemExit(1)
