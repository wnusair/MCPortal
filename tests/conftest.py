from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import ManagedPath, PermissionGrant, User
from app.security import hash_password


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "WTF_CSRF_ENABLED": False,
            "MAX_CONCURRENT_SESSIONS": 1,
            "PENDING_UPLOAD_DIR": str(tmp_path / "pending"),
            "BACKUP_DIR": str(tmp_path / "backups"),
            "RCON_PASSWORD": "test-password",
            "SERVER_NAME": "localhost",
        }
    )
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def user_factory(app):
    def create_user(
        username: str,
        password: str = "VerySecure123!",
        role: str = "viewer",
        parent: User | None = None,
    ) -> User:
        with app.app_context():
            user = User(
                username=username,
                password_hash=hash_password(password),
                role=role,
                parent_id=parent.id if parent else None,
            )
            db.session.add(user)
            db.session.commit()
            db.session.refresh(user)
            db.session.expunge(user)
            return user

    return create_user


@pytest.fixture()
def managed_path_factory(app, tmp_path: Path):
    def create_managed_path(
        label: str,
        *,
        path_type: str = "config",
        allow_view: bool = True,
        allow_edit: bool = False,
        allow_upload: bool = False,
    ) -> ManagedPath:
        absolute_path = tmp_path / label
        absolute_path.mkdir(parents=True, exist_ok=True)
        with app.app_context():
            managed_path = ManagedPath(
                label=label,
                absolute_path=str(absolute_path),
                path_type=path_type,
                allow_view=allow_view,
                allow_edit=allow_edit,
                allow_upload=allow_upload,
            )
            db.session.add(managed_path)
            db.session.commit()
            db.session.refresh(managed_path)
            db.session.expunge(managed_path)
            return managed_path

    return create_managed_path


@pytest.fixture()
def login(client):
    def do_login(username: str, password: str = "VerySecure123!"):
        return client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    return do_login


@pytest.fixture()
def grant_action(app):
    def create_action_grant(user: User, scope_value: str):
        with app.app_context():
            grant = PermissionGrant(
                user_id=user.id,
                scope_type="action",
                scope_value=scope_value,
                capability="access",
                effect="allow",
            )
            db.session.add(grant)
            db.session.commit()
            return grant

    return create_action_grant
