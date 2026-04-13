from __future__ import annotations

import secrets
from datetime import UTC, datetime
from functools import wraps

from flask import Flask, current_app, flash, redirect, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager
from app.models import User, UserSession
from app.services.audit import write_audit
from app.services.permissions import has_action_permission


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def verify_password(password_hash: str, candidate: str) -> bool:
    return check_password_hash(password_hash, candidate)


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))


def register_security(app: Flask) -> None:
    @login_manager.unauthorized_handler
    def unauthorized() -> str:
        flash("Sign in to continue.", "warning")
        return redirect(url_for("auth.login"))

    @app.before_request
    def bootstrap_guard() -> str | None:
        exempt_endpoints = {"auth.bootstrap", "static"}
        if User.query.count() == 0 and request.endpoint not in exempt_endpoints:
            return redirect(url_for("auth.bootstrap"))
        return None

    @app.before_request
    def validate_active_session() -> str | None:
        if not current_user.is_authenticated:
            return None

        session_token = session.get("sid")
        record = UserSession.query.filter_by(
            user_id=current_user.id,
            session_token=session_token,
            revoked_at=None,
        ).first()
        if not session_token or record is None:
            logout_current_session(logout_only=True)
            flash("Your session is no longer active.", "warning")
            return redirect(url_for("auth.login"))

        record.last_seen_at = utcnow()
        db.session.commit()
        return None


def start_authenticated_session(user: User) -> None:
    session.clear()
    login_user(user)
    session.permanent = True
    session_token = secrets.token_hex(24)
    session["sid"] = session_token

    record = UserSession(
        user_id=user.id,
        session_token=session_token,
        ip_address=request.remote_addr,
        user_agent=(request.user_agent.string or "")[:255],
    )
    db.session.add(record)
    db.session.commit()
    enforce_session_limit(user)


def logout_current_session(logout_only: bool = False) -> None:
    username = current_user.username if current_user.is_authenticated else "anonymous"
    if current_user.is_authenticated:
        session_token = session.get("sid")
        if session_token:
            record = UserSession.query.filter_by(
                user_id=current_user.id,
                session_token=session_token,
                revoked_at=None,
            ).first()
            if record:
                record.revoked_at = utcnow()
                db.session.commit()
    logout_user()
    session.clear()
    if not logout_only:
        write_audit("auth.logout", "user", username)


def enforce_session_limit(user: User) -> None:
    active_sessions = (
        UserSession.query.filter_by(user_id=user.id, revoked_at=None)
        .order_by(UserSession.last_seen_at.desc(), UserSession.created_at.desc())
        .all()
    )
    configured_limit = int(current_app.config["MAX_CONCURRENT_SESSIONS"])
    for record in active_sessions[configured_limit:]:
        record.revoked_at = utcnow()
    db.session.commit()


def action_required(action_key: str):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not has_action_permission(current_user, action_key):
                flash("You do not have access to that area.", "danger")
                return redirect(url_for("dashboard.index"))
            return view(*args, **kwargs)

        return wrapped

    return decorator

