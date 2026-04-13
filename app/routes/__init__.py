from flask import Flask

from app.routes.approvals import bp as approvals_bp
from app.routes.audit import bp as audit_bp
from app.routes.auth import bp as auth_bp
from app.routes.commands import bp as commands_bp
from app.routes.dashboard import bp as dashboard_bp
from app.routes.files import bp as files_bp
from app.routes.mods import bp as mods_bp
from app.routes.settings import bp as settings_bp
from app.routes.users import bp as users_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(commands_bp)
    app.register_blueprint(mods_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(approvals_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(audit_bp)
