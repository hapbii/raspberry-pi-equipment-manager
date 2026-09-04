from __future__ import annotations

import atexit
import logging
from pathlib import Path

from flask import Flask

from .config import Config
from .db import close_db, init_app_database
from .runtime import HeartbeatService


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

    from .web import bp

    app.register_blueprint(bp)

    with app.app_context():
        init_app_database()

    heartbeat = None
    if app.config.get("HEARTBEAT_ENABLED", True) and not app.config.get("TESTING", False):
        heartbeat = HeartbeatService(app)
        heartbeat.start()
        atexit.register(heartbeat.stop)

    app.extensions["heartbeat_service"] = heartbeat
    return app
