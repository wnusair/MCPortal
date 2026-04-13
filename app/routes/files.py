from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import FileEditForm
from app.models import ManagedPath
from app.services.approvals import create_pending_request
from app.services.audit import write_audit
from app.services.files import (
    FileAccessError,
    describe_path,
    list_archive_members,
    read_archive_text_preview,
    list_directory,
    read_text_file,
    read_text_preview,
    resolve_safe_path,
    write_text_file,
)
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
    if not target.exists():
        abort(404)

    edit_form = FileEditForm(prefix="edit")
    archive_member = request.args.get("member", "")

    file_details = describe_path(str(target))
    content = None
    entries = []
    archive_entries = []
    archive_preview = None
    supports_edit = bool(file_details["supports_edit"])
    if target.is_dir():
        entries = list_directory(managed_path.absolute_path, subpath)
    elif target.is_file():
        if supports_edit:
            content = read_text_file(str(target))
        elif file_details["preview_mode"] == "text":
            content = read_text_preview(str(target))
        elif file_details["preview_mode"] == "archive":
            try:
                archive_entries = list_archive_members(str(target))
                if archive_member:
                    archive_preview = read_archive_text_preview(str(target), archive_member)
            except FileAccessError:
                if archive_member:
                    flash("That archive entry could not be opened.", "danger")
                    return redirect(url_for("files.browse", path_id=path_id, subpath=subpath))
                archive_entries = []
                file_details["preview_mode"] = "raw"

    if request.method == "GET" and supports_edit and content is not None:
        edit_form.content.data = content

    if request.method == "POST" and supports_edit and content is not None:
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
        file_details=file_details,
        content=content,
        archive_entries=archive_entries,
        archive_preview=archive_preview,
        can_edit=supports_edit and has_path_capability(current_user, str(target), "edit"),
        supports_edit=supports_edit,
        edit_form=edit_form,
    )


@bp.route("/<int:path_id>/raw")
@login_required
def raw(path_id: int):
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
    if not target.exists() or not target.is_file():
        abort(404)

    download = request.args.get("download") == "1"
    return send_file(
        str(target),
        as_attachment=download,
        conditional=True,
        download_name=target.name,
    )
