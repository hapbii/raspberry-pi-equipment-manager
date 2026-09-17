"""Cheap status reads: never load a model or open a camera while rendering."""
from pathlib import Path

from flask import current_app

from .vision import get_detection_service


def recognition_status() -> dict:
    status = get_detection_service().status()
    mode = current_app.config["DETECTOR_MODE"]
    model = Path(current_app.config["YOLO_MODEL_PATH"]).expanduser()
    if not model.is_absolute():
        model = Path(current_app.root_path).parent / model
    state = status["check_state"]
    model_exists = model.exists()
    allowed = mode == "yolo" and model_exists and not status["closed"]
    if status["closed"]:
        state = "closed"
    elif mode != "yolo":
        state = "mock"
    elif not model_exists:
        state = "model_missing"
    elif status["busy"]:
        state = "busy"
    labels = {
        "closed": ("인식 서비스 종료", "서버를 다시 시작해 주세요."),
        "mock": ("모의 인식 모드", "모델과 카메라 준비 후 .env에서 yolo 모드로 변경해 주세요."),
        "model_missing": ("모델 파일 없음", "학습한 모델을 넣고 YOLO_MODEL_PATH를 확인해 주세요."),
        "busy": ("인식·점검 중", "현재 작업이 끝날 때까지 기다려 주세요."),
        "unchecked": ("카메라·모델 점검 전", "모델 경로는 확인됐습니다. 개발자 점검 또는 첫 인식이 필요합니다."),
        "ready": ("최근 인식·점검 성공", "마지막 검사 결과입니다. 현재 연결 상태를 보장하지는 않습니다."),
        "camera_error": ("카메라 점검 실패", "카메라 연결을 확인하고 다시 점검해 주세요."),
        "inference_error": ("인식 확인 필요", "물체 위치·조명·모델 설정을 확인하고 다시 시도해 주세요."),
    }
    title, message = labels[state]
    return {"state": state, "title": title, "message": message,
            "can_scan": allowed, "checked_at": status["checked_at"]}
