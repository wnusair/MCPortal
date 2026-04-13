from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import ManagedActionForm, ManagedPathForm, SystemSettingsForm
from app.models import ManagedAction, ManagedPath
from app.services.audit import write_audit
from app.services.permissions import has_action_permission
from app.services.system_settings import get_setting, set_setting


bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if not current_user.is_superadmin and not has_action_permission(current_user, "settings.manage"):
        flash("You do not have access to settings.", "danger")
        return redirect(url_for("dashboard.index"))

    path_form = ManagedPathForm(prefix="path")
    action_form = ManagedActionForm(prefix="action")
    system_form = SystemSettingsForm(prefix="system")

    if request.method == "GET":
        system_form.rcon_host.data = get_setting("rcon_host") or "127.0.0.1"
        system_form.rcon_port.data = get_setting("rcon_port") or "25575"
        system_form.pending_upload_dir.data = get_setting(
            "pending_upload_dir",
            current_app.config["PENDING_UPLOAD_DIR"],
        )
        system_form.backup_dir.data = get_setting("backup_dir", current_app.config["BACKUP_DIR"])

    if request.method == "POST" and "path-submit" in request.form and path_form.validate_on_submit():
        managed_path = ManagedPath(
            label=path_form.label.data,
            absolute_path=path_form.absolute_path.data,
            path_type=path_form.path_type.data,
            allow_view=path_form.allow_view.data,
            allow_edit=path_form.allow_edit.data,
            allow_upload=path_form.allow_upload.data,
        )
        db.session.add(managed_path)
        db.session.commit()
        write_audit("settings.managed_path_added", "managed_path", managed_path.label, actor=current_user)
        flash("Managed path added.", "success")
        return redirect(url_for("settings.index"))

    if request.method == "POST" and "action-submit" in request.form and action_form.validate_on_submit():
        managed_action = ManagedAction.query.filter_by(key=action_form.key.data).first()
        if managed_action is None:
            managed_action = ManagedAction(key=action_form.key.data, label=action_form.label.data)
            db.session.add(managed_action)

        managed_action.label = action_form.label.data
        managed_action.executable_path = action_form.executable_path.data
        managed_action.arguments_json = action_form.arguments_json.data or "[]"
        managed_action.working_directory = action_form.working_directory.data or None
        managed_action.enabled = True
        db.session.commit()
        write_audit(
            "settings.managed_action_saved",
            "managed_action",
            managed_action.key,
            actor=current_user,
        )
        flash("Managed action saved.", "success")
        return redirect(url_for("settings.index"))

    if request.method == "POST" and "system-submit" in request.form and system_form.validate_on_submit():
        try:
            int(system_form.rcon_port.data)
        except ValueError:
            flash("RCON port must be a number.", "danger")
            return redirect(url_for("settings.index"))

        set_setting("rcon_host", system_form.rcon_host.data)
        set_setting("rcon_port", system_form.rcon_port.data)
        if system_form.rcon_password.data:
            set_setting("rcon_password", system_form.rcon_password.data)
        set_setting("pending_upload_dir", system_form.pending_upload_dir.data)
        set_setting("backup_dir", system_form.backup_dir.data)
        current_app.config["RCON_HOST"] = system_form.rcon_host.data
        current_app.config["RCON_PORT"] = int(system_form.rcon_port.data)
        current_app.config["PENDING_UPLOAD_DIR"] = system_form.pending_upload_dir.data
        current_app.config["BACKUP_DIR"] = system_form.backup_dir.data
        Path(system_form.pending_upload_dir.data).mkdir(parents=True, exist_ok=True)
        Path(system_form.backup_dir.data).mkdir(parents=True, exist_ok=True)
        write_audit("settings.system_updated", "system", "minecraft", actor=current_user)
        flash("System settings updated.", "success")
        return redirect(url_for("settings.index"))

    return render_template(
        "settings/index.html",
        path_form=path_form,
        action_form=action_form,
        system_form=system_form,
        managed_paths=ManagedPath.query.order_by(ManagedPath.label.asc()).all(),
        managed_actions=ManagedAction.query.order_by(ManagedAction.label.asc()).all(),
    )
