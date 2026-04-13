from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import PermissionGrantForm, UserCreateForm
from app.models import PermissionGrant, User
from app.security import hash_password
from app.services.audit import write_audit
from app.services.permissions import can_create_underling, can_manage_user, has_action_permission, has_path_capability


bp = Blueprint("users", __name__, url_prefix="/users")


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if not current_user.is_superadmin and not has_action_permission(current_user, "users.view"):
        flash("You do not have access to user management.", "danger")
        return redirect(url_for("dashboard.index"))

    form = UserCreateForm(prefix="create")
    if request.method == "POST" and "create-submit" in request.form and form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first() is not None:
            flash("That username already exists.", "danger")
        elif not can_create_underling(current_user, form.role.data):
            flash("You do not have permission to create that user.", "danger")
        else:
            user = User(
                username=form.username.data,
                password_hash=hash_password(form.password.data),
                role=form.role.data,
                parent_id=current_user.id,
            )
            db.session.add(user)
            db.session.commit()
            write_audit("users.created", "user", user.username, actor=current_user)
            flash("User created.", "success")
            return redirect(url_for("users.permissions", user_id=user.id))

    if current_user.is_superadmin:
        users = User.query.order_by(User.created_at.asc()).all()
    else:
        users = User.query.filter((User.id == current_user.id) | (User.parent_id == current_user.id)).all()
    return render_template("users/index.html", form=form, users=users)


@bp.route("/<int:user_id>/permissions", methods=["GET", "POST"])
@login_required
def permissions(user_id: int):
    target_user = db.session.get(User, user_id)
    if target_user is None:
        abort(404)
    if not can_manage_user(current_user, target_user):
        flash("You cannot manage that account.", "danger")
        return redirect(url_for("users.index"))

    form = PermissionGrantForm(prefix="grant")
    if request.method == "POST" and "grant-submit" in request.form and form.validate_on_submit():
        scope_value = form.scope_value.data.strip()
        if form.scope_type.data == "action" and not current_user.is_superadmin:
            if form.effect.data == "allow" and not has_action_permission(current_user, scope_value):
                flash("You cannot grant action access that you do not have.", "danger")
                return redirect(url_for("users.permissions", user_id=target_user.id))

        if form.scope_type.data == "path" and not current_user.is_superadmin:
            if form.effect.data == "allow" and not has_path_capability(
                current_user,
                scope_value,
                form.capability.data,
            ):
                flash("You cannot grant path access that you do not have.", "danger")
                return redirect(url_for("users.permissions", user_id=target_user.id))

        grant = PermissionGrant.query.filter_by(
            user_id=target_user.id,
            scope_type=form.scope_type.data,
            scope_value=scope_value,
            capability=form.capability.data,
        ).first()
        if grant is None:
            grant = PermissionGrant(
                user_id=target_user.id,
                scope_type=form.scope_type.data,
                scope_value=scope_value,
                capability=form.capability.data,
                effect=form.effect.data,
            )
            db.session.add(grant)
        else:
            grant.effect = form.effect.data
        db.session.commit()
        write_audit(
            "users.permissions_updated",
            "user",
            target_user.username,
            actor=current_user,
            details={
                "scope_type": form.scope_type.data,
                "scope_value": scope_value,
                "capability": form.capability.data,
                "effect": form.effect.data,
            },
        )
        flash("Permission grant saved.", "success")
        return redirect(url_for("users.permissions", user_id=target_user.id))

    grants = target_user.permission_grants.order_by(PermissionGrant.scope_type.asc()).all()
    return render_template("users/permissions.html", form=form, target_user=target_user, grants=grants)


@bp.route("/<int:user_id>/permissions/<int:grant_id>/delete", methods=["POST"])
@login_required
def delete_permission(user_id: int, grant_id: int):
    target_user = db.session.get(User, user_id)
    grant = db.session.get(PermissionGrant, grant_id)
    if target_user is None or grant is None or grant.user_id != target_user.id:
        abort(404)
    if not can_manage_user(current_user, target_user):
        flash("You cannot manage that account.", "danger")
        return redirect(url_for("users.index"))

    db.session.delete(grant)
    db.session.commit()
    write_audit("users.permission_deleted", "user", target_user.username, actor=current_user)
    flash("Permission grant removed.", "success")
    return redirect(url_for("users.permissions", user_id=target_user.id))
