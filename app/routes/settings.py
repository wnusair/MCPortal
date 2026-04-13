from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import ManagedActionForm, SystemSettingsForm
from app.models import ManagedAction, ManagedPath
from app.services.audit import write_audit
from app.services.permissions import has_action_permission
from app.services.server_setup import sync_server_root
from app.services.system_settings import get_setting, set_setting


bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if not current_user.is_superadmin and not has_action_permission(current_user, "settings.manage"):
        flash("You do not have access to settings.", "danger")
        return redirect(url_for("dashboard.index"))

    action_form = ManagedActionForm(prefix="action")
    system_form = SystemSettingsForm(prefix="system")

    if request.method == "GET":
        system_form.server_root.data = get_setting("server_root", "") or ""
        system_form.rcon_host.data = get_setting("rcon_host") or "127.0.0.1"
        system_form.rcon_port.data = get_setting("rcon_port") or "25575"
        system_form.pending_upload_dir.data = get_setting(
            "pending_upload_dir",
            current_app.config["PENDING_UPLOAD_DIR"],
        )
        system_form.backup_dir.data = get_setting("backup_dir", current_app.config["BACKUP_DIR"])

    if request.method == "POST" and "path-submit" in request.form:
        flash(
            "Managed paths now sync from the Minecraft server directory. Update system settings to refresh them.",
            "info",
        )
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

        server_root = (system_form.server_root.data or "").strip()
        set_setting("server_root", server_root)
        set_setting("rcon_host", system_form.rcon_host.data)
        set_setting("rcon_port", system_form.rcon_port.data)
        if system_form.rcon_password.data:
            set_setting("rcon_password", system_form.rcon_password.data)
        set_setting("pending_upload_dir", system_form.pending_upload_dir.data)
        set_setting("backup_dir", system_form.backup_dir.data)
        current_app.config["SERVER_ROOT"] = server_root
        current_app.config["RCON_HOST"] = system_form.rcon_host.data
        current_app.config["RCON_PORT"] = int(system_form.rcon_port.data)
        if system_form.rcon_password.data:
            current_app.config["RCON_PASSWORD"] = system_form.rcon_password.data
        current_app.config["PENDING_UPLOAD_DIR"] = system_form.pending_upload_dir.data
        current_app.config["BACKUP_DIR"] = system_form.backup_dir.data
        Path(system_form.pending_upload_dir.data).mkdir(parents=True, exist_ok=True)
        Path(system_form.backup_dir.data).mkdir(parents=True, exist_ok=True)

        sync_result = None
        if server_root:
            sync_result = sync_server_root(server_root)
            if sync_result.imported_rcon_port:
                set_setting("rcon_host", "127.0.0.1")
                set_setting("rcon_port", sync_result.imported_rcon_port)
                current_app.config["RCON_HOST"] = "127.0.0.1"
                current_app.config["RCON_PORT"] = int(sync_result.imported_rcon_port)
            if sync_result.imported_rcon_password:
                set_setting("rcon_password", sync_result.imported_rcon_password)
                current_app.config["RCON_PASSWORD"] = sync_result.imported_rcon_password

        details = {"server_root": server_root}
        if sync_result is not None:
            details.update(
                {
                    "created_paths": sync_result.created_paths,
                    "updated_paths": sync_result.updated_paths,
                    "deleted_paths": sync_result.deleted_paths,
                    "created_actions": sync_result.created_actions,
                }
            )
        write_audit("settings.system_updated", "system", "minecraft", actor=current_user, details=details)
        flash("System settings updated.", "success")
        if sync_result is not None:
            flash(
                (
                    "Server folder synced: "
                    f"{sync_result.created_paths} new paths, "
                    f"{sync_result.updated_paths} updated paths, "
                    f"{sync_result.deleted_paths} removed paths, "
                    f"{sync_result.created_actions} new actions."
                ),
                "info",
            )
            if sync_result.imported_rcon_port or sync_result.imported_rcon_password:
                flash("Imported RCON settings from server.properties.", "info")
        return redirect(url_for("settings.index"))

    return render_template(
        "settings/index.html",
        action_form=action_form,
        system_form=system_form,
        managed_paths=ManagedPath.query.order_by(ManagedPath.label.asc()).all(),
        managed_actions=ManagedAction.query.order_by(ManagedAction.label.asc()).all(),
    )
