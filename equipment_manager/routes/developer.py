from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, render_template

from ..db import get_db
from ..system_metrics import current_rss_mb
from ..vision import get_detection_service
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
    )
