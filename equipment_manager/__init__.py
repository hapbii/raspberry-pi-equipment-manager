from __future__ import annotations

import atexit
import logging
import threading
from pathlib import Path

from flask import Flask

from .config import Config
from .db import close_db, init_app_database
from .runtime import HeartbeatService
from .vision import build_detection_service


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config["DATABASE"] = str(Path(app.config["DATABASE"]).expanduser().resolve())

    logging.basicConfig(
        level=getattr(logging, app.config["LOG_LEVEL"].upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app.teardown_appcontext(close_db)

    from .routes import bp

    app.register_blueprint(bp)
    detection_service = build_detection_service(app.config)
    app.extensions["detection_service"] = detection_service

    with app.app_context():
        init_app_database()

    heartbeat = None
    if app.config.get("HEARTBEAT_ENABLED", True) and not app.config.get("TESTING", False):
        heartbeat = HeartbeatService(app)
        heartbeat.start()

    app.extensions["heartbeat_service"] = heartbeat
    shutdown_lock = threading.Lock()
    shutdown_complete = False

    def shutdown_services() -> None:
        nonlocal shutdown_complete
        with shutdown_lock:
            if shutdown_complete:
                return
            shutdown_complete = True
            if heartbeat is not None:
                heartbeat.stop()
            detection_service.close()
            indicator = app.extensions.get("status_indicator")
            if indicator is not None:
                indicator.close()

    if not app.config.get("TESTING", False):
        atexit.register(shutdown_services)
    app.extensions["shutdown_services"] = shutdown_services
    return app
