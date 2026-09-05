from __future__ import annotations

import secrets
from functools import wraps

from flask import current_app, flash, jsonify, redirect, request, session, url_for

from . import bp


@bp.before_app_request
def ensure_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(24)


@bp.app_context_processor
def inject_template_context():
    station_auth_required = current_app.config["STATION_AUTH_REQUIRED"]
    admin_role = session.get("admin_role")
    teacher_password = current_app.config["TEACHER_PASSWORD"]
    return {
        "csrf_token": session.get("csrf_token", ""),
        "detector_mode": current_app.config["DETECTOR_MODE"],
        "station_auth_required": station_auth_required,
        "admin_authenticated": admin_role in {"teacher", "developer"},
        "admin_role": admin_role,
        "is_developer": admin_role == "developer",
        "admin_role_label": {
            "teacher": "선생님 관리자",
            "developer": "개발자 관리자",
        }.get(admin_role, ""),
        "using_default_secrets": current_app.config["DEVELOPER_PASSWORD"]
        in {"admin1234", "developer1234"}
        or teacher_password == "teacher1234"
        or (
            station_auth_required
            and current_app.config["STATION_PIN"] == "1234"
        ),
    }


def is_api_request() -> bool:
    return request.path.startswith("/api/")


def csrf_valid() -> bool:
    if not current_app.config.get("CSRF_ENABLED", True):
        return True
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    return bool(supplied and expected and secrets.compare_digest(supplied, expected))


@bp.before_app_request
def protect_post_requests():
    if request.method == "POST" and not csrf_valid():
        if is_api_request():
            return jsonify({"ok": False, "error": "요청 보안 토큰이 올바르지 않습니다."}), 400
        flash("요청 보안 토큰이 올바르지 않습니다. 다시 시도해 주세요.", "error")
        return redirect(request.referrer or url_for("web.dashboard"))
    return None


def station_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if (
            not current_app.config["STATION_AUTH_REQUIRED"]
            or session.get("admin_role") == "developer"
        ):
            return view(*args, **kwargs)
        if not session.get("station_authenticated"):
            if is_api_request():
                return jsonify({"ok": False, "error": "인식 스테이션 로그인이 필요합니다."}), 401
            return redirect(url_for("web.station_login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("admin_role") not in {"teacher", "developer"}:
            if is_api_request():
                return jsonify({"ok": False, "error": "관리자 로그인이 필요합니다."}), 401
            return redirect(url_for("web.admin_login"))
        return view(*args, **kwargs)

    return wrapped


def developer_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        role = session.get("admin_role")
        if role != "developer":
            if is_api_request():
                return jsonify({"ok": False, "error": "개발자 권한이 필요합니다."}), 403
            if role == "teacher":
                flash("이 화면은 개발자 계정만 사용할 수 있습니다.", "error")
                return redirect(url_for("web.admin_page"))
            return redirect(url_for("web.admin_login"))
        return view(*args, **kwargs)

    return wrapped
