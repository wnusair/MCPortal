from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db, limiter
from app.forms import BootstrapForm, LoginForm, PasswordChangeForm
from app.models import User
from app.security import hash_password, logout_current_session, start_authenticated_session, verify_password
from app.services.audit import write_audit


bp = Blueprint("auth", __name__)


@bp.route("/bootstrap", methods=["GET", "POST"])
def bootstrap():
    if User.query.count() > 0:
        return redirect(url_for("auth.login"))

    form = BootstrapForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            password_hash=hash_password(form.password.data),
            role="superadmin",
        )
        db.session.add(user)
        db.session.commit()
        write_audit("auth.bootstrap", "user", user.username, actor=user)
        start_authenticated_session(user)
        flash("Superadmin account created.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/bootstrap.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not verify_password(user.password_hash, form.password.data):
            write_audit(
                "auth.login_failed",
                "user",
                form.username.data,
                status="error",
            )
            flash("Invalid username or password.", "danger")
        else:
            start_authenticated_session(user)
            write_audit("auth.login", "user", user.username, actor=user)
            flash("Signed in.", "success")
            return redirect(url_for("dashboard.index"))

    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_current_session()
    flash("Signed out.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=["GET", "POST"])
@login_required
def password():
    form = PasswordChangeForm()
    if form.validate_on_submit():
        if not verify_password(current_user.password_hash, form.current_password.data):
            flash("Current password is incorrect.", "danger")
        else:
            current_user.password_hash = hash_password(form.new_password.data)
            db.session.commit()
            write_audit("auth.password_changed", "user", current_user.username, actor=current_user)
            flash("Password updated.", "success")
            return redirect(url_for("dashboard.index"))

    return render_template("auth/password.html", form=form)
