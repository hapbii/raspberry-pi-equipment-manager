from __future__ import annotations

from datetime import datetime, timezone

from flask import current_app, jsonify, render_template

from ..db import get_db, utc_now
from ..inventory import list_inventory
from ..system_metrics import current_rss_mb
from ..vision import get_detection_service
from . import bp


@bp.get("/")
def dashboard():
    return render_template("dashboard.html", inventory=list_inventory())


@bp.get("/healthz")
def healthz():
    try:
        db = get_db()
        db.execute("SELECT 1").fetchone()
        journal_mode = str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    return jsonify(
        {
            "ok": True,
            "time": utc_now(),
            "database": {"engine": "sqlite", "journal_mode": journal_mode},
            "memory_rss_mb": current_rss_mb(),
            "inference": get_detection_service().status(),
        }
    )


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
            "inference": get_detection_service().status(),
        }
    )
