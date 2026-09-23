from __future__ import annotations

import csv
import io

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for

from ..equipment_settings import change_selected_equipment
from ..inventory import (
    InventoryError,
    OUTSTANDING_PAGE_SIZE,
    add_equipment,
    deactivate_equipment,
    delete_transaction_record,
    list_inventory,
    list_outstanding,
    list_transactions,
    outstanding_summary,
    reverse_transaction,
    update_equipment,
)
from ..security import constant_time_equal
from ..auth import RateLimited, begin_session, clear_attempt, end_session, take_attempt
from . import bp
from .common import admin_required, developer_required


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        supplied_username = request.form.get("username", "").strip()[:80]
        supplied = request.form.get("password", "")
        try:
            take_attempt("login-ip", request.remote_addr or "local", limit=60)
            bucket = take_attempt("admin-login", supplied_username)
        except RateLimited as exc:
            flash(str(exc), "error")
            return render_template("login.html"), 429, {"Retry-After": str(exc.retry_after)}
        developer_valid = constant_time_equal(
            supplied_username,
            current_app.config["DEVELOPER_USERNAME"],
        ) and constant_time_equal(
            supplied, current_app.config["DEVELOPER_PASSWORD"]
        )
        teacher_username = current_app.config["TEACHER_USERNAME"]
        teacher_password = current_app.config["TEACHER_PASSWORD"]
        teacher_valid = bool(
            teacher_username
            and teacher_password
            and constant_time_equal(supplied_username, teacher_username)
            and constant_time_equal(supplied, teacher_password)
        )
        role = "developer" if developer_valid else "teacher" if teacher_valid else None
        if role:
            clear_attempt(bucket)
            begin_session(role, supplied_username, current_app.config[f"{role.upper()}_PASSWORD"])
            role_name = "개발자 관리자" if role == "developer" else "선생님 관리자"
            flash(f"{role_name}로 로그인했습니다.", "success")
            return redirect(url_for("web.admin_page"))
        flash("관리자 아이디 또는 비밀번호가 올바르지 않습니다.", "error")
    return render_template("login.html")


@bp.post("/admin/logout")
def admin_logout():
    end_session()
    flash("관리자 로그아웃을 완료했습니다.", "success")
    return redirect(url_for("web.dashboard"))


@bp.get("/admin")
@admin_required
def admin_page():
    query = request.args.get("q", "").strip()[:80]
    page = max(1, min(request.args.get("loans_page", 1, type=int), 100000))
    outstanding = list_outstanding(OUTSTANDING_PAGE_SIZE + 1, (page - 1) * OUTSTANDING_PAGE_SIZE)
    summary = outstanding_summary()
    return render_template(
        "admin.html",
        inventory=list_inventory(),
        outstanding=outstanding[:OUTSTANDING_PAGE_SIZE],
        loans_page=page,
        loans_has_next=len(outstanding) > OUTSTANDING_PAGE_SIZE,
        outstanding_quantity=summary["quantity"],
        overdue_student_count=summary["overdue_student_count"],
        transactions=list_transactions(150, query),
        query=query,
    )


@bp.post("/admin/equipment")
@admin_required
def admin_add_equipment():
    try:
        add_equipment(
            request.form.get("name", ""),
            int(request.form.get("total_qty", "")),
            int(request.form.get("loan_period_days", "")),
        )
        flash("새 기자재 종류를 추가했습니다.", "success")
    except (ValueError, InventoryError) as exc:
        flash(str(exc) or "수량과 대여 기간을 숫자로 입력해 주세요.", "error")
    return redirect(url_for("web.admin_page"))


@bp.post("/api/admin/equipment/batch")
@admin_required
def admin_batch_equipment():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False, error="요청 형식이 올바르지 않습니다."), 400
    try:
        rows = change_selected_equipment(data.get("action"), data.get("items"))
    except InventoryError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    return jsonify(ok=True, items=rows)


@bp.post("/admin/equipment/<int:equipment_id>")
@admin_required
def admin_update_equipment(equipment_id: int):
    try:
        total_qty = int(request.form.get("total_qty", ""))
        available_qty = int(request.form.get("available_qty", ""))
        loan_period_days = int(request.form.get("loan_period_days", ""))
        update_equipment(equipment_id, total_qty, available_qty, loan_period_days)
        flash("기자재 수량과 대여 기간을 수정했습니다.", "success")
    except (ValueError, InventoryError) as exc:
        flash(str(exc) or "수량과 대여 기간을 숫자로 입력해 주세요.", "error")
    return redirect(url_for("web.admin_page"))


@bp.post("/admin/equipment/<int:equipment_id>/remove")
@admin_required
def admin_remove_equipment(equipment_id: int):
    try:
        deactivate_equipment(equipment_id)
        flash("기자재 종류를 제거했습니다. 기존 거래 기록은 보존됩니다.", "success")
    except InventoryError as exc:
        flash(str(exc), "error")
    return redirect(url_for("web.admin_page"))


@bp.post("/admin/transactions/<transaction_id>/reverse")
@admin_required
def admin_reverse_transaction(transaction_id: str):
    try:
        actor = f"{session.get('admin_role', 'admin')}:{session.get('admin_username', '')}"
        reverse_transaction(transaction_id, reversed_by=actor[:80])
        flash("거래를 취소하고 기자재 수량을 복구했습니다.", "success")
    except InventoryError as exc:
        flash(str(exc), "error")
    return redirect(url_for("web.admin_page"))


@bp.post("/admin/transactions/<transaction_id>/delete")
@developer_required
def admin_delete_transaction(transaction_id: str):
    try:
        delete_transaction_record(transaction_id)
        flash("취소된 거래 기록을 영구 삭제했습니다.", "success")
    except InventoryError as exc:
        flash(str(exc), "error")
    return redirect(url_for("web.admin_page"))


@bp.get("/admin/export.csv")
@admin_required
def admin_export_csv():
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(
        ["거래ID", "학번", "기자재", "구분", "수량", "반납예정일", "신뢰도", "처리시각", "취소시각", "대여사유"]
    )
    for row in list_transactions(500):
        writer.writerow(
            [_csv_safe_value(value) for value in [
                row["id"],
                row["student_id"],
                row["equipment_name"],
                row["action"],
                row["quantity"],
                row["due_date"] or "",
                row["confidence"],
                row["created_at"],
                row["reversed_at"] or "",
                row["reason"],
            ]]
        )
    return current_app.response_class(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=equipment-transactions.csv"},
    )


def _csv_safe_value(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
