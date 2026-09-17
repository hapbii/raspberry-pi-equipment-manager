from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, flash, g, redirect, render_template, request, url_for

from ..auth import RateLimited, take_attempt
from ..db import get_db
from ..error_logs import get_error_log_store
from ..power import poweroff_available, schedule_poweroff
from ..security import constant_time_equal
from ..system_metrics import current_rss_mb
from ..vision import DetectionError, get_detection_service
from . import bp
from .common import developer_required


@bp.get("/developer")
@developer_required
def developer_page():
    db = get_db()
    database_path = Path(current_app.config["DATABASE"])
    model_path = Path(current_app.config["YOLO_MODEL_PATH"]).expanduser()
    if not model_path.is_absolute():
        model_path = Path(current_app.root_path).parent / model_path

    return render_template(
        "developer.html",
        memory_rss_mb=current_rss_mb(),
        database_path=database_path,
        database_size_mb=(
            database_path.stat().st_size / (1024 * 1024)
            if database_path.is_file()
            else 0
        ),
        journal_mode=str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
        sqlite_version=sqlite3.sqlite_version,
        inference=get_detection_service().status(),
        model_path=model_path,
        model_exists=model_path.exists(),
        error_log=get_error_log_store().snapshot(),
        poweroff_available=poweroff_available(),
    )


@bp.post("/developer/error-logs/clear")
@developer_required
def developer_clear_error_logs():
    try:
        get_error_log_store().clear()
        flash("오류 로그를 모두 삭제했습니다.", "success")
    except OSError:
        current_app.logger.exception("Failed to clear the error log")
        flash("오류 로그를 삭제하지 못했습니다. 파일 권한을 확인해 주세요.", "error")
    return redirect(f"{url_for('web.developer_page')}#error-logs")


@bp.post("/developer/recognition-check")
@developer_required
def developer_recognition_check():
    try:
        get_detection_service().preflight()
        flash("모델·카메라 점검을 통과했습니다.", "success")
    except DetectionError as exc:
        flash(f"인식 점검 실패: {exc}", "error")
    except Exception:
        current_app.logger.exception("Recognition preflight failed")
        flash("인식 점검에 실패했습니다. 오류 로그를 확인해 주세요.", "error")
    return redirect(url_for("web.developer_page"))


@bp.route("/developer/poweroff", methods=["GET", "POST"])
@developer_required
def developer_poweroff():
    available = poweroff_available()
    if request.method == "GET":
        return render_template("poweroff.html", available=available, scheduled=False)
    if not available:
        return render_template("poweroff.html", available=False, scheduled=False,
                               error="종료 기능을 먼저 설치해 주세요."), 503
    if request.form.get("confirmation") != "poweroff":
        return render_template("poweroff.html", available=True, scheduled=False,
                               error="종료 영향 안내를 확인하고 체크해 주세요."), 400
    try:
        take_attempt("poweroff", g.user["name"], limit=5, seconds=300)
    except RateLimited:
        return render_template("poweroff.html", available=True, scheduled=False,
                               error="요청이 너무 많습니다. 5분 뒤 다시 시도해 주세요."), 429
    if not constant_time_equal(request.form.get("password", ""), current_app.config["DEVELOPER_PASSWORD"]):
        return render_template("poweroff.html", available=True, scheduled=False,
                               error="개발자 비밀번호가 올바르지 않습니다."), 400
    try:
        schedule_poweroff()
    except RuntimeError as exc:
        current_app.logger.exception("Raspberry Pi shutdown request failed")
        return render_template("poweroff.html", available=True, scheduled=False, error=str(exc)), 503
    current_app.logger.warning("Raspberry Pi shutdown timer requested by developer")
    return render_template("poweroff.html", available=True, scheduled=True), 202
