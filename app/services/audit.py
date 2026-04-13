from __future__ import annotations

from flask import has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog, User


def write_audit(
    action: str,
    target_type: str,
    target_name: str,
    *,
    actor: User | None = None,
    status: str = "ok",
    details: dict | None = None,
) -> AuditLog:
    resolved_actor = actor
    if resolved_actor is None and has_request_context() and getattr(current_user, "is_authenticated", False):
        resolved_actor = current_user

    entry = AuditLog(
        actor=resolved_actor,
        action=action,
        target_type=target_type,
        target_name=target_name,
        status=status,
        ip_address=request.remote_addr if has_request_context() else None,
        details_json=details or {},
    )
    db.session.add(entry)
    db.session.commit()
    return entry
