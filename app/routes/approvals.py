from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import ReviewRequestForm
from app.models import PendingRequest
from app.services.approvals import review_pending_request
from app.services.permissions import has_action_permission


bp = Blueprint("approvals", __name__, url_prefix="/approvals")


@bp.route("/")
@login_required
def index():
    if not current_user.is_superadmin and not has_action_permission(current_user, "approvals.review"):
        flash("You do not have access to approvals.", "danger")
        return redirect(url_for("dashboard.index"))

    pending_requests = (
        PendingRequest.query.filter_by(status="pending")
        .order_by(PendingRequest.created_at.asc())
        .all()
    )
    forms = {item.id: ReviewRequestForm(prefix=f"review-{item.id}") for item in pending_requests}
    return render_template("approvals/index.html", pending_requests=pending_requests, forms=forms)


@bp.route("/<int:request_id>/review", methods=["POST"])
@login_required
def review(request_id: int):
    if not current_user.is_superadmin and not has_action_permission(current_user, "approvals.review"):
        flash("You do not have access to approvals.", "danger")
        return redirect(url_for("dashboard.index"))

    pending_request = db.session.get(PendingRequest, request_id)
    if pending_request is None:
        abort(404)

    form = ReviewRequestForm(prefix=f"review-{request_id}")
    if form.validate_on_submit():
        approve = bool(form.approve.data)
        try:
            review_pending_request(
                pending_request,
                current_user,
                approve=approve,
                review_note=form.review_note.data,
            )
            flash("Pending request reviewed.", "success")
        except Exception as exc:
            flash(str(exc), "danger")

    return redirect(url_for("approvals.index"))
