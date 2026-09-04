from __future__ import annotations

import argparse
import gc
import statistics
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
    scan_count = max(1, args.scans)

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
    rss_samples: list[float] = []
    successes = 0
    failures = 0
    interrupted = False
    print(f"예열 후 기준 RSS: {baseline} MB")
    print("실제 기자재 하나를 촬영 구역에 계속 놓아 두세요.")

    try:
        for index in range(1, scan_count + 1):
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
            if rss is not None:
                rss_samples.append(rss)
            print(f"{index:03d}/{scan_count} RSS={rss} MB | {summary}")
            time.sleep(max(0, args.interval))
    except KeyboardInterrupt:
        interrupted = True
        print("\n사용자가 검사를 중지했습니다.")
    finally:
        live_final = current_rss_mb()
        app.extensions["shutdown_services"]()
        gc.collect()
        after_close = current_rss_mb()

    growth = None if baseline is None or live_final is None else live_final - baseline
    trend = None
    if rss_samples:
        window = min(10, max(1, len(rss_samples) // 4))
        trend = statistics.median(rss_samples[-window:]) - statistics.median(
            rss_samples[:window]
        )
    print(f"\n성공 {successes}회 / 실패 {failures}회")
    print(f"최고 RSS: {peak} MB")
    print(f"서비스 실행 중 마지막 RSS: {live_final} MB / 기준 대비 증가량: {growth} MB")
    print(f"앞·뒤 구간 중앙값 증가량: {trend} MB / 서비스 종료 후 RSS: {after_close} MB")
    if interrupted:
        return 130
    if growth is None or trend is None:
        print("실패: RSS 값을 읽지 못해 메모리 누수를 판정할 수 없습니다.")
        return 1
    if max(growth, trend) > args.max_growth_mb:
        print("실패: 서비스 실행 중 RSS 증가량이 기준을 초과했습니다.")
        return 1
    print("통과: RSS 증가량이 설정 기준 이내입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
