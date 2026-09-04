from __future__ import annotations

import secrets
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .db import get_db, set_device_status, utc_now
from .detectors import DetectionError, get_detector
from .hardware import get_indicator
from .inventory import (
    InventoryError,
    add_equipment,
    commit_transaction,
    create_scan_session,
    find_equipment_by_name,
    get_equipment,
    list_inventory,
    list_outstanding,
    list_transactions,
    reverse_transaction,
    update_equipment,
)


bp = Blueprint("web", __name__)


@bp.before_app_request
def ensure_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(24)


@bp.app_context_processor
def inject_template_context():
    return {
        "csrf_token": session.get("csrf_token", ""),
        "detector_mode": current_app.config["DETECTOR_MODE"],
        "using_default_secrets": current_app.config["ADMIN_PASSWORD"] == "admin1234"
        or current_app.config["STATION_PIN"] == "1234",
    }


def _is_api_request() -> bool:
    return request.path.startswith("/api/")


def _csrf_valid() -> bool:
    if not current_app.config.get("CSRF_ENABLED", True):
        return True
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    return bool(supplied and expected and secrets.compare_digest(supplied, expected))


@bp.before_app_request
def protect_post_requests():
    if request.method == "POST" and not _csrf_valid():
        if _is_api_request():
            return jsonify({"ok": False, "error": "요청 보안 토큰이 올바르지 않습니다."}), 400
        flash("요청 보안 토큰이 올바르지 않습니다. 다시 시도해 주세요.", "error")
        return redirect(request.referrer or url_for("web.dashboard"))
    return None


def station_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("station_authenticated"):
            if _is_api_request():
                return jsonify({"ok": False, "error": "인식 스테이션 로그인이 필요합니다."}), 401
            return redirect(url_for("web.station_login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            if _is_api_request():
                return jsonify({"ok": False, "error": "관리자 로그인이 필요합니다."}), 401
            return redirect(url_for("web.admin_login"))
        return view(*args, **kwargs)

    return wrapped


@bp.get("/")
def dashboard():
    return render_template("dashboard.html", inventory=list_inventory())


@bp.get("/healthz")
def healthz():
    try:
        get_db().execute("SELECT 1").fetchone()
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    return jsonify({"ok": True, "time": utc_now()})


@bp.get("/api/status")
def api_status():
    row = get_db().execute("SELECT * FROM device_status WHERE id = 1").fetchone()
    now = datetime.now(timezone.utc)
    device = dict(row) if row else {}
    last_seen = device.get("last_seen")
    online = False
    if last_seen:
        try:
            age = (now - datetime.fromisoformat(last_seen)).total_seconds()
            online = age <= current_app.config["DEVICE_OFFLINE_SECONDS"]
        except ValueError:
            online = False
    device["online"] = online
    return jsonify(
        {
            "ok": True,
            "server_time": now.isoformat(timespec="seconds"),
            "inventory": list_inventory(),
            "device": device,
        }
    )


@bp.route("/station/login", methods=["GET", "POST"])
def station_login():
    if request.method == "POST":
        supplied = request.form.get("pin", "")
        if secrets.compare_digest(supplied, current_app.config["STATION_PIN"]):
            session["station_authenticated"] = True
            flash("인식 스테이션에 로그인했습니다.", "success")
            return redirect(url_for("web.scan_page"))
        flash("스테이션 PIN이 올바르지 않습니다.", "error")
    return render_template("login.html", mode="station")


@bp.post("/station/logout")
def station_logout():
    session.pop("station_authenticated", None)
    flash("인식 스테이션에서 로그아웃했습니다.", "success")
    return redirect(url_for("web.dashboard"))


@bp.get("/scan")
@station_required
def scan_page():
    return render_template("scan.html", inventory=list_inventory())


@bp.post("/api/scans")
@station_required
def api_create_scan():
    data = request.get_json(silent=True) or {}
    category_hint = None
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
        detection = get_detector().detect(category_hint)
        equipment = find_equipment_by_name(detection.label)
        if not equipment:
            aliases = current_app.config.get("YOLO_CLASS_ALIASES", {})
            configured = ", ".join(item["name"] for item in list_inventory())
            raise DetectionError(
                f"모델 클래스 '{detection.label}'이 DB 기자재와 일치하지 않습니다. "
                f"등록된 이름: {configured}. 클래스 별칭 설정도 확인해 주세요: {aliases}"
            )
        scan = create_scan_session(equipment["id"], detection.confidence)
        set_device_status()
        get_indicator().success()
        return jsonify(
            {
                "ok": True,
                "scan": scan,
                "votes": detection.votes,
                "frame_count": detection.frame_count,
            }
        )
    except (DetectionError, InventoryError) as exc:
        set_device_status(str(exc))
        get_indicator().error()
        return jsonify({"ok": False, "error": str(exc)}), 422
    except Exception as exc:
        current_app.logger.exception("Unexpected scan failure")
        set_device_status(str(exc))
        get_indicator().error()
        return jsonify({"ok": False, "error": "인식 중 예상하지 못한 오류가 발생했습니다."}), 500


@bp.post("/api/transactions")
@station_required
def api_create_transaction():
    data = request.get_json(silent=True) or {}
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


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        supplied = request.form.get("password", "")
        if secrets.compare_digest(supplied, current_app.config["ADMIN_PASSWORD"]):
            session["admin_authenticated"] = True
            flash("관리자로 로그인했습니다.", "success")
            return redirect(url_for("web.admin_page"))
        flash("관리자 비밀번호가 올바르지 않습니다.", "error")
    return render_template("login.html", mode="admin")


@bp.post("/admin/logout")
def admin_logout():
    session.pop("admin_authenticated", None)
    flash("관리자 로그아웃을 완료했습니다.", "success")
    return redirect(url_for("web.dashboard"))


@bp.get("/admin")
@admin_required
def admin_page():
    query = request.args.get("q", "").strip()
    return render_template(
        "admin.html",
        inventory=list_inventory(),
        outstanding=list_outstanding(),
        transactions=list_transactions(150, query),
        query=query,
    )


@bp.post("/admin/equipment")
@admin_required
def admin_add_equipment():
    try:
        add_equipment(request.form.get("name", ""), int(request.form.get("total_qty", "")))
        flash("새 기자재 종류를 추가했습니다.", "success")
    except (ValueError, InventoryError) as exc:
        flash(str(exc) or "수량을 숫자로 입력해 주세요.", "error")
    return redirect(url_for("web.admin_page"))


@bp.post("/admin/equipment/<int:equipment_id>")
@admin_required
def admin_update_equipment(equipment_id: int):
    try:
        total_qty = int(request.form.get("total_qty", ""))
        available_qty = int(request.form.get("available_qty", ""))
        update_equipment(equipment_id, total_qty, available_qty)
        flash("기자재 수량을 수정했습니다.", "success")
    except (ValueError, InventoryError) as exc:
        flash(str(exc) or "수량을 숫자로 입력해 주세요.", "error")
    return redirect(url_for("web.admin_page"))


@bp.post("/admin/transactions/<transaction_id>/reverse")
@admin_required
def admin_reverse_transaction(transaction_id: str):
    try:
        reverse_transaction(transaction_id)
        flash("거래를 취소하고 재고를 복구했습니다.", "success")
    except InventoryError as exc:
        flash(str(exc), "error")
    return redirect(url_for("web.admin_page"))


@bp.get("/admin/export.csv")
@admin_required
def admin_export_csv():
    import csv
    import io

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["거래ID", "학번", "기자재", "구분", "수량", "신뢰도", "처리시각", "취소시각"])
    for row in list_transactions(500):
        writer.writerow(
            [
                row["id"],
                row["student_id"],
                row["equipment_name"],
                row["action"],
                row["quantity"],
                row["confidence"],
                row["created_at"],
                row["reversed_at"] or "",
            ]
        )
    return current_app.response_class(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=equipment-transactions.csv"},
    )
