from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import FileEditForm
from app.models import ManagedPath
from app.services.approvals import create_pending_request
from app.services.audit import write_audit
from app.services.files import FileAccessError, list_directory, read_text_file, resolve_safe_path, write_text_file
from app.services.permissions import has_path_capability


bp = Blueprint("files", __name__, url_prefix="/files")


@bp.route("/")
@login_required
def index():
    visible_paths = [
        managed_path
        for managed_path in ManagedPath.query.order_by(ManagedPath.label.asc()).all()
        if has_path_capability(current_user, managed_path.absolute_path, "view")
    ]
    return render_template("files/index.html", managed_paths=visible_paths)


@bp.route("/<int:path_id>", methods=["GET", "POST"])
@login_required
def browse(path_id: int):
    managed_path = db.session.get(ManagedPath, path_id)
    if managed_path is None:
        abort(404)

    subpath = request.args.get("subpath", "")
    try:
        target = resolve_safe_path(managed_path.absolute_path, subpath)
    except FileAccessError:
        flash("That path is not allowed.", "danger")
        return redirect(url_for("files.index"))
    if not has_path_capability(current_user, str(target), "view"):
        flash("You do not have access to that path.", "danger")
        return redirect(url_for("files.index"))

    edit_form = FileEditForm(prefix="edit")

    content = None
    entries = []
    is_text_file = target.is_file()
    if target.is_dir():
        entries = list_directory(managed_path.absolute_path, subpath)
        is_text_file = False
    elif target.exists() and target.is_file():
        try:
            content = read_text_file(str(target))
        except FileAccessError:
            content = None
            is_text_file = False

    if request.method == "GET" and content is not None:
        edit_form.content.data = content

    if request.method == "POST" and content is not None:
        if "suggest-submit" in request.form:
            suggestion_content = request.form.get("suggest-content", "")
            if suggestion_content.strip():
                create_pending_request(
                    "file_edit",
                    str(target),
                    {"content": suggestion_content},
                    current_user,
                    target_name=target.name,
                )
                flash("Change request sent for approval.", "info")
                return redirect(url_for("files.browse", path_id=path_id, subpath=subpath))

            flash("Content is required.", "danger")
            edit_form.content.data = content

        if "edit-submit" in request.form and edit_form.validate_on_submit():
            if has_path_capability(current_user, str(target), "edit"):
                backup_path = write_text_file(str(target), edit_form.content.data)
                write_audit(
                    "files.edited",
                    "file",
                    str(target),
                    actor=current_user,
                    details={"backup_path": str(backup_path)},
                )
                flash("File updated.", "success")
            else:
                create_pending_request(
                    "file_edit",
                    str(target),
                    {"content": edit_form.content.data},
                    current_user,
                    target_name=target.name,
                )
                flash("Change request sent for approval.", "info")
            return redirect(url_for("files.browse", path_id=path_id, subpath=subpath))

    parent_subpath = ""
    if subpath:
        parent_subpath = str(Path(subpath).parent)
        if parent_subpath == ".":
            parent_subpath = ""

    return render_template(
        "files/detail.html",
        managed_path=managed_path,
        target=target,
        subpath=subpath,
        parent_subpath=parent_subpath,
        entries=entries,
        content=content,
        is_text_file=is_text_file,
        can_edit=has_path_capability(current_user, str(target), "edit"),
        edit_form=edit_form,
    )
