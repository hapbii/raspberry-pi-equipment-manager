from __future__ import annotations

from flask import current_app, jsonify, redirect, render_template, request, url_for

from ..db import set_device_status, utc_now
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
from ..auth import login_required, scan_owner, transaction_student_id
from ..vision import DetectionError, get_detection_service
from . import bp


@bp.route("/station/login", methods=["GET", "POST"])
def station_login():
    return redirect(url_for("web.student_login"))


@bp.post("/station/logout")
def station_logout():
    from ..auth import end_session
    end_session()
    return redirect(url_for("web.dashboard"))


@bp.get("/scan")
@login_required
def scan_page():
    return render_template("scan.html")


@bp.post("/api/scans")
@login_required
def api_create_scan():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="잘못된 요청입니다."), 400
    category_hint = None
    try:
        if str(data.get("action", "")) == "loan":
            check_student_loan_eligibility(transaction_student_id(data))
    except InventoryError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 422
    if current_app.config["DETECTOR_MODE"] == "mock":
        if not current_app.config["TESTING"]:
            return jsonify(ok=False, error="모의 모드에서는 실제 대여·반납 인식을 할 수 없습니다."), 422
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
        scan = create_scan_session(equipment["id"], detection.confidence, scan_owner())
        set_device_status(None)
        get_indicator().success()
        return jsonify(
            {
                "ok": True,
                "scan": scan,
                "server_time": utc_now(),
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
@login_required
def api_create_transaction():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="잘못된 요청입니다."), 400
    try:
        quantity = int(data.get("quantity", 1))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "수량이 올바르지 않습니다."}), 400
    try:
        result = commit_transaction(
            scan_token=str(data.get("scan_token", "")),
            student_id=transaction_student_id(data),
            action=str(data.get("action", "")),
            quantity=quantity,
            reason=data.get("reason", ""),
            owner_key=scan_owner(),
        )
        get_indicator().success()
        return jsonify({"ok": True, "transaction": result.__dict__})
    except InventoryError as exc:
        get_indicator().error()
        return jsonify({"ok": False, "error": str(exc)}), 422
