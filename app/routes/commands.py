from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.forms import CommandForm
from app.models import ManagedAction, PendingRequest
from app.services.approvals import create_pending_request
from app.services.audit import write_audit
from app.services.permissions import has_action_permission
from app.services.server_control import (
    ServerControlError,
    get_minecraft_server_status,
    run_managed_action,
    send_minecraft_command,
)


bp = Blueprint("commands", __name__, url_prefix="/commands")


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = CommandForm()
    output = None
    server_status = get_minecraft_server_status()

    if form.validate_on_submit():
        command = form.command.data
        if has_action_permission(current_user, "commands.execute"):
            try:
                output = send_minecraft_command(command)
                write_audit(
                    "commands.executed",
                    "minecraft_command",
                    command,
                    actor=current_user,
                    details={"output": output},
                )
                flash("Minecraft command executed.", "success")
            except ServerControlError as exc:
                flash(str(exc), "danger")
        else:
            create_pending_request(
                "command",
                command,
                {"command": command},
                current_user,
                target_name=command,
            )
            flash("Command request sent for approval.", "info")
            return redirect(url_for("commands.index"))

    requests = (
        PendingRequest.query.filter_by(requester_id=current_user.id)
        .order_by(PendingRequest.created_at.desc())
        .limit(8)
        .all()
    )
    actions = ManagedAction.query.filter_by(enabled=True).order_by(ManagedAction.label.asc()).all()
    return render_template(
        "commands/index.html",
        form=form,
        output=output,
        requests=requests,
        actions=actions,
        server_status=server_status,
    )


@bp.route("/actions/<action_key>", methods=["POST"])
@login_required
def run_action(action_key: str):
    if has_action_permission(current_user, f"server.actions.{action_key}") or has_action_permission(
        current_user,
        "server.actions.run",
    ):
        try:
            result = run_managed_action(action_key)
            write_audit(
                "server.action_executed",
                "managed_action",
                action_key,
                actor=current_user,
                details=result,
            )
            flash(f"Action {action_key} completed.", "success")
        except ServerControlError as exc:
            flash(str(exc), "danger")
    else:
        create_pending_request(
            "managed_action",
            action_key,
            {"action_key": action_key},
            current_user,
            target_name=action_key,
        )
        flash("Action request sent for approval.", "info")

    return redirect(url_for("commands.index"))
