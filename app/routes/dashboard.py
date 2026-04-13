from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.models import AuditLog, ManagedAction, ManagedPath, PendingRequest


bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    if current_user.is_superadmin:
        pending_count = PendingRequest.query.filter_by(status="pending").count()
        recent_audits = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(10).all()
    else:
        pending_count = PendingRequest.query.filter_by(
            requester_id=current_user.id,
            status="pending",
        ).count()
        recent_audits = (
            AuditLog.query.filter_by(actor_id=current_user.id)
            .order_by(AuditLog.created_at.desc())
            .limit(10)
            .all()
        )

    return render_template(
        "dashboard/index.html",
        pending_count=pending_count,
        managed_paths=ManagedPath.query.count(),
        managed_actions=ManagedAction.query.filter_by(enabled=True).count(),
        recent_audits=recent_audits,
        actions=ManagedAction.query.filter_by(enabled=True).order_by(ManagedAction.label.asc()).all(),
    )
