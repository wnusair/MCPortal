from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from app.config import Config
from app.extensions import csrf, db, limiter, login_manager, talisman
from app.routes import register_blueprints
from app.security import register_security
from app.services.permissions import has_action_permission


def create_app(config_object: type[Config] | dict | None = None) -> Flask:
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    if isinstance(config_object, dict):
        app.config.update(config_object)
    elif config_object is not None:
        app.config.from_object(config_object)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["PENDING_UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["BACKUP_DIR"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    talisman.init_app(
        app,
        content_security_policy=app.config["CONTENT_SECURITY_POLICY"],
        force_https=False,
        session_cookie_secure=app.config["SESSION_COOKIE_SECURE"],
    )

    register_security(app)
    register_blueprints(app)

    with app.app_context():
        from app import models  # noqa: F401

        db.create_all()

    @app.context_processor
    def inject_shell() -> dict[str, str]:
        return {
            "app_name": "MCPortal",
            "has_action_permission": has_action_permission,
        }

    return app
