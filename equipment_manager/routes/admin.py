from __future__ import annotations

import csv
import io
import secrets

from flask import current_app, flash, redirect, render_template, request, session, url_for

from ..inventory import (
    InventoryError,
    add_equipment,
    list_inventory,
    list_outstanding,
    list_transactions,
    reverse_transaction,
    update_equipment,
)
from . import bp
from .common import admin_required


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        supplied_username = request.form.get("username", "").strip()
        supplied = request.form.get("password", "")
        developer_valid = secrets.compare_digest(
            supplied_username,
            current_app.config["DEVELOPER_USERNAME"],
        ) and secrets.compare_digest(
            supplied, current_app.config["DEVELOPER_PASSWORD"]
        )
        teacher_username = current_app.config["TEACHER_USERNAME"]
        teacher_password = current_app.config["TEACHER_PASSWORD"]
        teacher_valid = bool(
            teacher_username
            and teacher_password
            and secrets.compare_digest(supplied_username, teacher_username)
            and secrets.compare_digest(supplied, teacher_password)
        )
        role = "developer" if developer_valid else "teacher" if teacher_valid else None
        if role:
            session["admin_role"] = role
            session["admin_username"] = supplied_username
            role_name = "개발자 관리자" if role == "developer" else "선생님 관리자"
            flash(f"{role_name}로 로그인했습니다.", "success")
            return redirect(url_for("web.admin_page"))
        flash("관리자 아이디 또는 비밀번호가 올바르지 않습니다.", "error")
    return render_template("login.html", mode="admin")


@bp.post("/admin/logout")
def admin_logout():
    session.pop("admin_role", None)
    session.pop("admin_username", None)
    flash("관리자 로그아웃을 완료했습니다.", "success")
    return redirect(url_for("web.dashboard"))


@bp.get("/admin")
@admin_required
def admin_page():
    query = request.args.get("q", "").strip()[:80]
    outstanding = list_outstanding()
    return render_template(
        "admin.html",
        inventory=list_inventory(),
        outstanding=outstanding,
        overdue_student_count=len(
            {row["student_id"] for row in outstanding if row["overdue"]}
        ),
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
        actor = f"{session.get('admin_role', 'admin')}:{session.get('admin_username', '')}"
        reverse_transaction(transaction_id, reversed_by=actor[:80])
        flash("거래를 취소하고 재고를 복구했습니다.", "success")
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
        ["거래ID", "학번", "기자재", "구분", "수량", "반납예정일", "신뢰도", "처리시각", "취소시각"]
    )
    for row in list_transactions(500):
        writer.writerow(
            [
                row["id"],
                row["student_id"],
                row["equipment_name"],
                row["action"],
                row["quantity"],
                row["due_date"] or "",
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
