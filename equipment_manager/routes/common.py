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
    return {
        "csrf_token": session.get("csrf_token", ""),
        "detector_mode": current_app.config["DETECTOR_MODE"],
        "station_auth_required": station_auth_required,
        "admin_authenticated": session.get("admin_authenticated", False),
        "using_default_secrets": current_app.config["ADMIN_PASSWORD"] == "admin1234"
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
        if not current_app.config["STATION_AUTH_REQUIRED"]:
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
        if not session.get("admin_authenticated"):
            if is_api_request():
                return jsonify({"ok": False, "error": "관리자 로그인이 필요합니다."}), 401
            return redirect(url_for("web.admin_login"))
        return view(*args, **kwargs)

    return wrapped
