from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import ModUploadForm
from app.models import ManagedPath, StagedUpload
from app.services.approvals import create_pending_request
from app.services.audit import write_audit
from app.services.permissions import has_path_capability
from app.services.uploads import UploadError, promote_staged_upload, stage_upload


bp = Blueprint("mods", __name__, url_prefix="/mods")


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = ModUploadForm()
    destinations = ManagedPath.query.filter_by(path_type="mods").order_by(ManagedPath.label.asc()).all()
    form.destination_id.choices = [(item.id, item.label) for item in destinations]

    if form.validate_on_submit():
        destination = db.session.get(ManagedPath, form.destination_id.data)
        if destination is None:
            flash("Choose a valid mods directory.", "danger")
            return redirect(url_for("mods.index"))

        try:
            staged_upload = stage_upload(form.upload.data, destination.absolute_path, current_user)
            if has_path_capability(current_user, destination.absolute_path, "upload"):
                target = promote_staged_upload(staged_upload)
                write_audit(
                    "mods.promoted_directly",
                    "mod_upload",
                    staged_upload.original_filename,
                    actor=current_user,
                    details={"destination": str(target)},
                )
                flash("Mod uploaded directly to the managed mods folder.", "success")
            else:
                pending_request = create_pending_request(
                    "mod_upload",
                    destination.absolute_path,
                    {"staged_upload_id": staged_upload.id},
                    current_user,
                    target_name=staged_upload.original_filename,
                )
                staged_upload.pending_request_id = pending_request.id
                db.session.commit()
                flash("Mod upload staged for superadmin approval.", "info")
        except UploadError as exc:
            flash(str(exc), "danger")

        return redirect(url_for("mods.index"))

    uploads = (
        StagedUpload.query.order_by(StagedUpload.created_at.desc())
        .limit(12 if current_user.is_superadmin else 6)
        .all()
    )
    if not current_user.is_superadmin:
        uploads = [item for item in uploads if item.requester_id == current_user.id]

    return render_template("mods/index.html", form=form, destinations=destinations, uploads=uploads)
