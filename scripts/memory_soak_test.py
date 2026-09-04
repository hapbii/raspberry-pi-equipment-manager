from __future__ import annotations

import argparse
import gc
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from equipment_manager import create_app  # noqa: E402
from equipment_manager.system_metrics import current_rss_mb  # noqa: E402
from equipment_manager.vision import DetectionError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="실제 카메라와 YOLO 반복 추론 메모리 점검")
    parser.add_argument("--scans", type=int, default=50, help="반복 횟수")
    parser.add_argument("--interval", type=float, default=0.3, help="반복 간 대기 시간")
    parser.add_argument("--max-growth-mb", type=float, default=120.0, help="허용할 RSS 증가량")
    args = parser.parse_args()

    app = create_app({"HEARTBEAT_ENABLED": False})
    if app.config["DETECTOR_MODE"] != "yolo":
        print(".env의 DETECTOR_MODE를 yolo로 변경하세요.")
        app.extensions["shutdown_services"]()
        return 2

    service = app.extensions["detection_service"]
    print("모델·카메라 로딩과 메모리 할당 안정화를 위해 3회 예열합니다.")
    try:
        service.preflight()
        for _ in range(3):
            try:
                service.detect()
            except DetectionError:
                pass
    except DetectionError as exc:
        print(f"사전 점검 실패: {exc}")
        app.extensions["shutdown_services"]()
        return 1

    gc.collect()
    baseline = current_rss_mb()
    peak = baseline
    successes = 0
    failures = 0
    print(f"예열 후 기준 RSS: {baseline} MB")
    print("실제 기자재 하나를 촬영 구역에 계속 놓아 두세요.")

    try:
        for index in range(1, max(1, args.scans) + 1):
            try:
                result = service.detect()
                successes += 1
                summary = f"{result.label} {result.confidence:.1%}"
            except DetectionError as exc:
                failures += 1
                summary = f"인식 실패: {exc}"
            rss = current_rss_mb()
            if rss is not None and (peak is None or rss > peak):
                peak = rss
            print(f"{index:03d}/{args.scans} RSS={rss} MB | {summary}")
            time.sleep(max(0, args.interval))
    finally:
        service.close()
        gc.collect()
        app.extensions["shutdown_services"]()

    final = current_rss_mb()
    growth = None if baseline is None or final is None else final - baseline
    print(f"\n성공 {successes}회 / 실패 {failures}회")
    print(f"최고 RSS: {peak} MB / 종료 RSS: {final} MB / 증가량: {growth} MB")
    if growth is not None and growth > args.max_growth_mb:
        print("실패: RSS 증가량이 기준을 초과했습니다.")
        return 1
    print("통과: RSS 증가량이 설정 기준 이내입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
