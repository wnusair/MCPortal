from __future__ import annotations

from datetime import UTC, datetime

from flask_login import UserMixin

from app.extensions import db


ROLE_PRECEDENCE = {
    "viewer": 1,
    "operator": 2,
    "admin": 3,
    "superadmin": 4,
}


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="viewer")
    parent_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    is_active_account = db.Column(db.Boolean, nullable=False, default=True)

    parent = db.relationship("User", remote_side=[id], backref=db.backref("children", lazy="select"))

    def get_id(self) -> str:
        return str(self.id)

    @property
    def is_active(self) -> bool:
        return self.is_active_account

    @property
    def is_superadmin(self) -> bool:
        return self.role == "superadmin"


class UserSession(TimestampMixin, db.Model):
    __tablename__ = "user_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    session_token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))
    last_seen_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    revoked_at = db.Column(db.DateTime)

    user = db.relationship("User", backref=db.backref("sessions", lazy="dynamic"))

    @property
    def is_active_record(self) -> bool:
        return self.revoked_at is None


class PermissionGrant(TimestampMixin, db.Model):
    __tablename__ = "permission_grants"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    scope_type = db.Column(db.String(16), nullable=False)
    scope_value = db.Column(db.String(512), nullable=False)
    capability = db.Column(db.String(64), nullable=False)
    effect = db.Column(db.String(8), nullable=False, default="allow")

    user = db.relationship("User", backref=db.backref("permission_grants", lazy="dynamic"))

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "scope_type",
            "scope_value",
            "capability",
            name="uq_permission_grant",
        ),
    )


class ManagedPath(TimestampMixin, db.Model):
    __tablename__ = "managed_paths"

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(64), unique=True, nullable=False)
    absolute_path = db.Column(db.String(1024), unique=True, nullable=False)
    path_type = db.Column(db.String(32), nullable=False, default="config")
    allow_view = db.Column(db.Boolean, nullable=False, default=True)
    allow_edit = db.Column(db.Boolean, nullable=False, default=False)
    allow_upload = db.Column(db.Boolean, nullable=False, default=False)


class ManagedAction(TimestampMixin, db.Model):
    __tablename__ = "managed_actions"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    label = db.Column(db.String(64), nullable=False)
    executable_path = db.Column(db.String(1024), nullable=False)
    arguments_json = db.Column(db.Text, nullable=False, default="[]")
    working_directory = db.Column(db.String(1024))
    enabled = db.Column(db.Boolean, nullable=False, default=True)


class SystemSetting(TimestampMixin, db.Model):
    __tablename__ = "system_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)


class PendingRequest(TimestampMixin, db.Model):
    __tablename__ = "pending_requests"

    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    request_type = db.Column(db.String(32), nullable=False)
    target = db.Column(db.String(1024), nullable=False)
    target_name = db.Column(db.String(255))
    payload_json = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(16), nullable=False, default="pending")
    review_note = db.Column(db.Text)
    reviewed_at = db.Column(db.DateTime)
    executed_at = db.Column(db.DateTime)
    error_message = db.Column(db.Text)

    requester = db.relationship("User", foreign_keys=[requester_id], backref="submitted_requests")
    reviewer = db.relationship("User", foreign_keys=[reviewer_id])


class StagedUpload(TimestampMixin, db.Model):
    __tablename__ = "staged_uploads"

    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    pending_request_id = db.Column(db.Integer, db.ForeignKey("pending_requests.id"), index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(1024), nullable=False)
    destination_path = db.Column(db.String(1024), nullable=False)
    checksum_sha256 = db.Column(db.String(64), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="pending")

    requester = db.relationship("User", backref="staged_uploads")
    pending_request = db.relationship("PendingRequest", backref="staged_upload")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    action = db.Column(db.String(128), nullable=False)
    target_type = db.Column(db.String(64), nullable=False)
    target_name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="ok")
    ip_address = db.Column(db.String(64))
    details_json = db.Column(db.JSON, nullable=False, default=dict)

    actor = db.relationship("User", backref="audit_entries")
