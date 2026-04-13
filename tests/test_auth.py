from __future__ import annotations

from app.models import User, UserSession


def test_bootstrap_and_password_change(client, app):
    response = client.post(
        "/bootstrap",
        data={
            "username": "root_admin",
            "password": "VerySecure123!",
            "confirm_password": "VerySecure123!",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(username="root_admin").first()
        assert user is not None
        assert user.role == "superadmin"

    response = client.post(
        "/password",
        data={
            "current_password": "VerySecure123!",
            "new_password": "ChangedPassword123!",
            "confirm_password": "ChangedPassword123!",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    client.post("/logout", data={}, follow_redirects=False)
    response = client.post(
        "/login",
        data={"username": "root_admin", "password": "ChangedPassword123!"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_login_rate_limit_blocks_repeated_failures(client, user_factory):
    user_factory("limited_user")

    for _ in range(5):
        response = client.post(
            "/login",
            data={"username": "limited_user", "password": "WrongPassword123!"},
            follow_redirects=False,
        )
        assert response.status_code == 200

    blocked = client.post(
        "/login",
        data={"username": "limited_user", "password": "WrongPassword123!"},
        follow_redirects=False,
    )
    assert blocked.status_code == 429


def test_session_limit_revokes_oldest_session(app, user_factory):
    user_factory("multi_user")

    first_client = app.test_client()
    second_client = app.test_client()

    first_login = first_client.post(
        "/login",
        data={"username": "multi_user", "password": "VerySecure123!"},
        follow_redirects=False,
    )
    assert first_login.status_code == 302

    second_login = second_client.post(
        "/login",
        data={"username": "multi_user", "password": "VerySecure123!"},
        follow_redirects=False,
    )
    assert second_login.status_code == 302

    expired_response = first_client.get("/", follow_redirects=False)
    assert expired_response.status_code == 302
    assert "/login" in expired_response.headers["Location"]

    with app.app_context():
        assert UserSession.query.filter_by(revoked_at=None).count() == 1
