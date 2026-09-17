from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for

from ..auth import (
    AccountError, RateLimited, authenticate_student, begin_session, clear_attempt,
    end_session, login_required, register_student, take_attempt, update_student_password,
)
from ..db import get_db
from . import bp
from .common import admin_required


def _limited_response(template, exc):
    flash(str(exc), "error")
    return render_template(template), 429, {"Retry-After": str(exc.retry_after)}


@bp.route("/register", methods=["GET", "POST"])
def student_register():
    if request.method == "POST":
        try:
            take_attempt("register-ip", request.remote_addr or "local", limit=20)
            password = request.form.get("password", "")
            if password != request.form.get("password_confirm", ""):
                raise AccountError("비밀번호 확인이 일치하지 않습니다.")
            register_student(request.form.get("student_id", "").strip(),
                             request.form.get("name", "").strip(), password)
            flash("가입 신청이 완료되었습니다. 선생님·개발자 승인 후 로그인할 수 있습니다.", "success")
            return redirect(url_for("web.student_login"))
        except RateLimited as exc:
            return _limited_response("register.html", exc)
        except AccountError as exc:
            flash(str(exc), "error")
    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        try:
            student_id = request.form.get("student_id", "").strip()[:20]
            take_attempt("login-ip", request.remote_addr or "local", limit=60)
            bucket = take_attempt("student-login", student_id)
            password = request.form.get("password", "")
            if len(password) > 128:
                raise AccountError("학번 또는 비밀번호가 올바르지 않습니다.")
            account = authenticate_student(student_id, password)
            clear_attempt(bucket)
            begin_session("student", str(account["id"]), account["password_hash"])
            return redirect(url_for("web.my_loans"))
        except RateLimited as exc:
            return _limited_response("student_login.html", exc)
        except (AccountError, UnicodeEncodeError) as exc:
            flash(str(exc) if isinstance(exc, AccountError) else "입력값을 확인해 주세요.", "error")
    return render_template("student_login.html")


@bp.post("/logout")
def user_logout():
    end_session()
    flash("로그아웃했습니다.", "success")
    return redirect(url_for("web.dashboard"))


@bp.get("/my-loans")
@login_required
def my_loans():
    if g.user["role"] != "student":
        return redirect(url_for("web.admin_page"))
    db = get_db()
    student_id = g.user["student_id"]
    outstanding = db.execute("""SELECT e.name, l.remaining_quantity, l.due_date
        FROM active_loans l JOIN equipment e ON e.id = l.equipment_id
        WHERE l.student_id = ? AND l.remaining_quantity > 0 ORDER BY l.due_date LIMIT 200""", (student_id,)).fetchall()
    history = db.execute("""SELECT t.action, t.quantity, t.reason, t.created_at, t.reversed_at, e.name
        FROM transactions t JOIN equipment e ON e.id = t.equipment_id
        WHERE t.student_id = ? ORDER BY t.created_at DESC, t.id DESC LIMIT 100""", (student_id,)).fetchall()
    return render_template("my_loans.html", outstanding=outstanding, history=history)


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def student_password():
    if g.user["role"] != "student":
        return redirect(url_for("web.admin_page"))
    if request.method == "POST":
        try:
            take_attempt("change-password", str(g.user["id"]))
            old = request.form.get("old_password", "")
            if len(old) > 128:
                raise AccountError("현재 비밀번호를 확인해 주세요.")
            authenticate_student(g.user["student_id"], old)
            new = request.form.get("password", "")
            if new != request.form.get("password_confirm", ""):
                raise AccountError("비밀번호 확인이 일치하지 않습니다.")
            update_student_password(g.user["id"], new)
            end_session()
            flash("비밀번호가 변경되었습니다. 모든 기기에서 로그아웃됐습니다. 다시 로그인해 주세요.", "success")
            return redirect(url_for("web.student_login"))
        except RateLimited as exc:
            return _limited_response("password.html", exc)
        except (AccountError, UnicodeEncodeError) as exc:
            flash(str(exc) if isinstance(exc, AccountError) else "입력값을 확인해 주세요.", "error")
    return render_template("password.html")


@bp.get("/admin/students")
@admin_required
def admin_students():
    page = max(1, min(request.args.get("page", 1, type=int), 100000))
    query = request.args.get("q", "").strip()[:40]
    rows = get_db().execute("""SELECT id, student_id, name, status, created_at FROM student_accounts
        WHERE student_id LIKE ? OR name LIKE ?
        ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, id DESC LIMIT 51 OFFSET ?""",
        (f"%{query}%", f"%{query}%", (page - 1) * 50)).fetchall()
    return render_template("students.html", students=rows[:50], has_next=len(rows) > 50, page=page, query=query)


@bp.post("/admin/students/<int:account_id>/<action>")
@admin_required
def admin_student_status(account_id, action):
    if action not in {"approve", "disable"}:
        return "잘못된 요청입니다.", 400
    db = get_db()
    with db:
        changed = db.execute("UPDATE student_accounts SET status = ? WHERE id = ?",
                            ("active" if action == "approve" else "disabled", account_id)).rowcount
        db.execute("DELETE FROM auth_sessions WHERE role = 'student' AND subject = ?", (str(account_id),))
    flash("학생 계정 상태를 변경했습니다." if changed else "계정을 찾을 수 없습니다.", "success" if changed else "error")
    return redirect(url_for("web.admin_students"))


@bp.route("/admin/students/<int:account_id>/password", methods=["GET", "POST"])
@admin_required
def admin_student_password(account_id):
    student = get_db().execute("SELECT id, student_id, name FROM student_accounts WHERE id = ?", (account_id,)).fetchone()
    if not student:
        return "학생 계정을 찾을 수 없습니다.", 404
    if request.method == "POST":
        try:
            take_attempt("password-reset", g.user["name"], limit=20)
            new = request.form.get("password", "")
            if new != request.form.get("password_confirm", ""):
                raise AccountError("비밀번호 확인이 일치하지 않습니다.")
            update_student_password(account_id, new)
            flash("비밀번호를 재설정하고 모든 기존 로그인을 종료했습니다. 학생에게 직접 전달해 주세요.", "success")
            return redirect(url_for("web.admin_students"))
        except RateLimited as exc:
            flash(str(exc), "error")
            return render_template("reset_password.html", student=student), 429, {"Retry-After": str(exc.retry_after)}
        except AccountError as exc:
            flash(str(exc), "error")
    return render_template("reset_password.html", student=student)
