from __future__ import annotations

import atexit
import logging
import threading
from pathlib import Path

from flask import Flask

from .config import Config
from .db import close_db, init_app_database
from .error_logs import ErrorLogStore
from .hardware import INDICATOR_KEY, init_hardware
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
    shutdown_lock = threading.Lock()
    shutdown_complete = False

    def shutdown_services() -> None:
        nonlocal shutdown_complete
        with shutdown_lock:
            if shutdown_complete:
                return
            shutdown_complete = True
            atexit.unregister(shutdown_services)
            # Keep logging alive until all other resources have been closed.
            for key, method in (
                ("heartbeat_service", "stop"),
                ("detection_service", "close"),
                (INDICATOR_KEY, "close"),
                ("error_log_store", "close"),
            ):
                service = app.extensions.pop(key, None)
                if service is None:
                    continue
                try:
                    getattr(service, method)()
                except Exception:
                    app.logger.exception("Failed to close %s service", key)

    app.extensions["shutdown_services"] = shutdown_services
    try:
        error_log_path = Path(app.config["ERROR_LOG_PATH"]).expanduser()
        if not error_log_path.is_absolute():
            error_log_path = Path(app.root_path).parent / error_log_path
        error_log_store = ErrorLogStore(
            error_log_path.resolve(),
            max_bytes=app.config["ERROR_LOG_MAX_BYTES"],
            backup_count=app.config["ERROR_LOG_BACKUP_COUNT"],
            display_bytes=app.config["ERROR_LOG_DISPLAY_BYTES"],
        )
        app.config["ERROR_LOG_PATH"] = str(error_log_store.path)
        app.extensions["error_log_store"] = error_log_store
        init_hardware(app)

        from .routes import bp

        app.register_blueprint(bp)
        app.extensions["detection_service"] = build_detection_service(app.config)
        with app.app_context():
            init_app_database()

        app.extensions["heartbeat_service"] = None
        if app.config.get("HEARTBEAT_ENABLED", True) and not app.config.get("TESTING", False):
            heartbeat = HeartbeatService(app)
            app.extensions["heartbeat_service"] = heartbeat
            heartbeat.start()
    except BaseException:
        shutdown_services()
        raise

    if not app.config.get("TESTING", False):
        atexit.register(shutdown_services)
    return app
