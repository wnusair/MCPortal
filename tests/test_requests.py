from __future__ import annotations

import io
from pathlib import Path

from app.models import PendingRequest, StagedUpload


def test_viewer_file_edit_becomes_pending_request(app, client, user_factory, managed_path_factory, login):
    user_factory("viewer_one")
    managed_path = managed_path_factory("config-root", allow_view=True, allow_edit=False)
    config_file = Path(managed_path.absolute_path) / "server.properties"
    config_file.write_text("motd=Original\n", encoding="utf-8")

    login("viewer_one")
    response = client.post(
        f"/files/{managed_path.id}?subpath=server.properties",
        data={"edit-content": "motd=Changed\n", "edit-submit": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert config_file.read_text(encoding="utf-8") == "motd=Original\n"
    with app.app_context():
        pending_request = PendingRequest.query.one()
        assert pending_request.request_type == "file_edit"
        assert pending_request.status == "pending"


def test_file_request_page_uses_single_editor_for_non_editors(client, user_factory, managed_path_factory, login):
    user_factory("viewer_request")
    managed_path = managed_path_factory("request-root", allow_view=True, allow_edit=False)
    config_file = Path(managed_path.absolute_path) / "server.properties"
    config_file.write_text("motd=Original\n", encoding="utf-8")

    login("viewer_request")
    response = client.get(f"/files/{managed_path.id}?subpath=server.properties")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Request a change" in page
    assert "Alternate suggestion" not in page
    assert 'name="edit-content"' in page
    assert 'name="suggest-content"' not in page


def test_path_traversal_is_rejected(client, user_factory, managed_path_factory, login, tmp_path):
    user_factory("viewer_two")
    managed_path = managed_path_factory("safe-root", allow_view=True)
    secret_file = tmp_path / "outside.txt"
    secret_file.write_text("secret", encoding="utf-8")

    login("viewer_two")
    response = client.get(f"/files/{managed_path.id}?subpath=../outside.txt", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/files/")


def test_superadmin_approval_applies_file_change(app, client, user_factory, managed_path_factory, login):
    superadmin = user_factory("root_admin", role="superadmin")
    viewer = user_factory("viewer_three", parent=superadmin)
    managed_path = managed_path_factory("approval-root", allow_view=True, allow_edit=False)
    config_file = Path(managed_path.absolute_path) / "fabric-server.toml"
    config_file.write_text("enabled=true\n", encoding="utf-8")

    client.post(
        "/login",
        data={"username": viewer.username, "password": "VerySecure123!"},
        follow_redirects=False,
    )
    client.post(
        f"/files/{managed_path.id}?subpath=fabric-server.toml",
        data={"edit-content": "enabled=false\n", "edit-submit": "1"},
        follow_redirects=False,
    )
    client.post("/logout", data={}, follow_redirects=False)

    login("root_admin")
    with app.app_context():
        request_id = PendingRequest.query.one().id
    response = client.post(
        f"/approvals/{request_id}/review",
        data={f"review-{request_id}-review_note": "Looks good", f"review-{request_id}-approve": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert config_file.read_text(encoding="utf-8") == "enabled=false\n"
    with app.app_context():
        assert PendingRequest.query.one().status == "executed"


def test_mod_upload_is_staged_when_user_lacks_upload_permission(app, client, user_factory, managed_path_factory, login):
    user_factory("viewer_mod")
    mods_path = managed_path_factory("mods-root", path_type="mods", allow_view=True, allow_upload=False)

    login("viewer_mod")
    response = client.post(
        "/mods/",
        data={
            "destination_id": str(mods_path.id),
            "upload": (io.BytesIO(b"jar-content"), "example-mod.jar"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    with app.app_context():
        upload = StagedUpload.query.one()
        request = PendingRequest.query.one()
        assert upload.original_filename == "example-mod.jar"
        assert request.request_type == "mod_upload"
        assert Path(upload.stored_path).exists()


def test_command_without_permission_creates_pending_request(client, user_factory, login, app):
    user_factory("viewer_cmd")
    login("viewer_cmd")

    response = client.post(
        "/commands/",
        data={"command": "/say hello world"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    with app.app_context():
        pending_request = PendingRequest.query.one()
        assert pending_request.request_type == "command"
        assert pending_request.target_name == "/say hello world"
