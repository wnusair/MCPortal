from __future__ import annotations

import json
import re
from pathlib import Path

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import BooleanField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, EqualTo, Length, Optional, ValidationError


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


def validate_username_format(form: FlaskForm, field: StringField) -> None:
    if not USERNAME_RE.fullmatch(field.data or ""):
        raise ValidationError("Use 3-32 letters, numbers, or underscores.")


def validate_absolute_path(form: FlaskForm, field: StringField) -> None:
    candidate = Path(field.data or "")
    if not candidate.is_absolute():
        raise ValidationError("An absolute path is required.")


def validate_json_args(form: FlaskForm, field: TextAreaField) -> None:
    try:
        value = json.loads(field.data or "[]")
    except json.JSONDecodeError as exc:
        raise ValidationError("Arguments must be valid JSON.") from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationError("Arguments must be a JSON array of strings.")


class BootstrapForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), validate_username_format])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=12, max=128)])
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password")],
    )
    submit = SubmitField("Create superadmin")


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), validate_username_format])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=12, max=128)])
    submit = SubmitField("Sign in")


class PasswordChangeForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField("New password", validators=[DataRequired(), Length(min=12, max=128)])
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("new_password")],
    )
    submit = SubmitField("Update password")


class UserCreateForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), validate_username_format])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=12, max=128)])
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password")],
    )
    role = SelectField(
        "Role",
        choices=[
            ("viewer", "Viewer"),
            ("operator", "Operator"),
            ("admin", "Admin"),
        ],
        validators=[DataRequired()],
    )
    submit = SubmitField("Create user")


class PermissionGrantForm(FlaskForm):
    scope_type = SelectField(
        "Scope type",
        choices=[("action", "Action"), ("path", "Path")],
        validators=[DataRequired()],
    )
    scope_value = StringField("Scope value", validators=[DataRequired(), Length(max=512)])
    capability = SelectField(
        "Capability",
        choices=[
            ("access", "Action access"),
            ("view", "View path"),
            ("edit", "Edit path"),
            ("upload", "Upload into path"),
        ],
        validators=[DataRequired()],
    )
    effect = SelectField(
        "Effect",
        choices=[("allow", "Allow"), ("deny", "Deny")],
        validators=[DataRequired()],
    )
    submit = SubmitField("Save grant")


class ManagedPathForm(FlaskForm):
    label = StringField("Label", validators=[DataRequired(), Length(max=64)])
    absolute_path = StringField("Absolute path", validators=[DataRequired(), validate_absolute_path])
    path_type = SelectField(
        "Type",
        choices=[("config", "Config"), ("mods", "Mods"), ("data", "Data")],
        validators=[DataRequired()],
    )
    allow_view = BooleanField("Allow view", default=True)
    allow_edit = BooleanField("Allow direct edit")
    allow_upload = BooleanField("Allow upload")
    submit = SubmitField("Add managed path")


class ManagedActionForm(FlaskForm):
    key = StringField("Action key", validators=[DataRequired(), Length(max=64)])
    label = StringField("Label", validators=[DataRequired(), Length(max=64)])
    executable_path = StringField("Executable path", validators=[DataRequired(), validate_absolute_path])
    arguments_json = TextAreaField("Arguments (JSON)", validators=[Optional(), validate_json_args])
    working_directory = StringField("Working directory", validators=[Optional(), validate_absolute_path])
    submit = SubmitField("Save action")


class SystemSettingsForm(FlaskForm):
    rcon_host = StringField("RCON host", validators=[DataRequired(), Length(max=255)])
    rcon_port = StringField("RCON port", validators=[DataRequired(), Length(max=16)])
    rcon_password = PasswordField("RCON password", validators=[Optional(), Length(max=255)])
    pending_upload_dir = StringField(
        "Pending upload directory",
        validators=[DataRequired(), validate_absolute_path],
    )
    backup_dir = StringField("Backup directory", validators=[DataRequired(), validate_absolute_path])
    submit = SubmitField("Update settings")


class CommandForm(FlaskForm):
    command = StringField("Minecraft command", validators=[DataRequired(), Length(max=512)])
    submit = SubmitField("Send")


class FileEditForm(FlaskForm):
    content = TextAreaField("Content", validators=[DataRequired()])
    submit = SubmitField("Save")


class FileSuggestionForm(FlaskForm):
    content = TextAreaField("Proposed content", validators=[DataRequired()])
    submit = SubmitField("Submit for approval")


class ModUploadForm(FlaskForm):
    destination_id = SelectField("Destination", coerce=int, validators=[DataRequired()])
    upload = FileField(
        "Upload mod",
        validators=[FileRequired(), FileAllowed(["jar"], "Only .jar files are allowed.")],
    )
    submit = SubmitField("Upload")


class ReviewRequestForm(FlaskForm):
    review_note = TextAreaField("Review note", validators=[Optional(), Length(max=2000)])
    approve = SubmitField("Approve")
    reject = SubmitField("Reject")
