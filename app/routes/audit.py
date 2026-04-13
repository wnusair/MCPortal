from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.models import AuditLog
from app.services.permissions import has_action_permission


bp = Blueprint("audit", __name__, url_prefix="/audit")


@bp.route("/")
@login_required
def index():
    query = AuditLog.query.order_by(AuditLog.created_at.desc())
    if not current_user.is_superadmin and not has_action_permission(current_user, "audit.view"):
        query = query.filter_by(actor_id=current_user.id)
    entries = query.limit(100).all()
    return render_template("audit/index.html", entries=entries)