from __future__ import annotations

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for

from ..db import set_device_status
from ..hardware import get_indicator
from ..inventory import (
    InventoryError,
    check_student_loan_eligibility,
    commit_transaction,
    create_scan_session,
    find_equipment_by_name,
    get_equipment,
    list_inventory,
)
from ..security import constant_time_equal
from ..vision import DetectionError, get_detection_service
from . import bp


@bp.route("/station/login", methods=["GET", "POST"])
def station_login():
    flash("스테이션 PIN은 최종 대여·반납 처리 단계에서 입력합니다.", "success")
    return redirect(url_for("web.scan_page"))


@bp.post("/station/logout")
def station_logout():
    flash("스테이션 PIN은 거래마다 최종 처리 단계에서 확인합니다.", "success")
    return redirect(url_for("web.dashboard"))


@bp.get("/scan")
def scan_page():
    return render_template("scan.html", inventory=list_inventory())


@bp.post("/api/scans")
def api_create_scan():
    data = request.get_json(silent=True) or {}
    category_hint = None
    try:
        if str(data.get("action", "")) == "loan":
            check_student_loan_eligibility(str(data.get("student_id", "")))
    except InventoryError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 422
    if current_app.config["DETECTOR_MODE"] == "mock":
        try:
            equipment_id = int(data.get("mock_equipment_id", 0))
        except (TypeError, ValueError):
            equipment_id = 0
        equipment = get_equipment(equipment_id)
        if not equipment:
            return jsonify({"ok": False, "error": "모의 인식용 기자재를 선택해 주세요."}), 400
        category_hint = equipment["name"]

    try:
        detection = get_detection_service().detect(category_hint)
        equipment = find_equipment_by_name(detection.label)
        if not equipment:
            aliases = current_app.config.get("YOLO_CLASS_ALIASES", {})
            configured = ", ".join(item["name"] for item in list_inventory())
            raise DetectionError(
                f"모델 클래스 '{detection.label}'이 DB 기자재와 일치하지 않습니다. "
                f"등록된 이름: {configured}. 클래스 별칭 설정도 확인해 주세요: {aliases}"
            )
        scan = create_scan_session(equipment["id"], detection.confidence)
        set_device_status(None)
        get_indicator().success()
        return jsonify(
            {
                "ok": True,
                "scan": scan,
                "votes": detection.votes,
                "frame_count": detection.frame_count,
                "duration_ms": detection.duration_ms,
                "memory_rss_mb": detection.memory_rss_mb,
            }
        )
    except DetectionError as exc:
        current_app.logger.error("Object detection failed: %s", exc)
        set_device_status(str(exc))
        get_indicator().error()
        return jsonify({"ok": False, "error": str(exc)}), 422
    except InventoryError as exc:
        set_device_status(str(exc))
        get_indicator().error()
        return jsonify({"ok": False, "error": str(exc)}), 422
    except Exception as exc:
        current_app.logger.exception("Unexpected scan failure")
        set_device_status(str(exc))
        get_indicator().error()
        return jsonify({"ok": False, "error": "인식 중 예상하지 못한 오류가 발생했습니다."}), 500


@bp.post("/api/transactions")
def api_create_transaction():
    data = request.get_json(silent=True) or {}
    pin_required = (
        current_app.config["STATION_AUTH_REQUIRED"]
        and session.get("admin_role") != "developer"
    )
    if pin_required:
        supplied_pin = str(data.get("station_pin") or "")[:128]
        if not constant_time_equal(supplied_pin, current_app.config["STATION_PIN"]):
            return (
                jsonify(
                    {
                        "ok": False,
                        "code": "station_pin_invalid",
                        "error": "스테이션 PIN이 올바르지 않습니다.",
                    }
                ),
                403,
            )
    try:
        quantity = int(data.get("quantity", 1))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "수량이 올바르지 않습니다."}), 400
    try:
        result = commit_transaction(
            scan_token=str(data.get("scan_token", "")),
            student_id=str(data.get("student_id", "")),
            action=str(data.get("action", "")),
            quantity=quantity,
        )
        get_indicator().success()
        return jsonify({"ok": True, "transaction": result.__dict__})
    except InventoryError as exc:
        get_indicator().error()
        return jsonify({"ok": False, "error": str(exc)}), 422
