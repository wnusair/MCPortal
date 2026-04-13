from __future__ import annotations

from pathlib import Path

from app.models import ManagedAction, ManagedPath, PermissionGrant


def test_user_permissions_page_shows_effective_permissions(
    app,
    client,
    user_factory,
    managed_path_factory,
    grant_action,
    login,
):
    superadmin = user_factory("root_owner", role="superadmin")
    child = user_factory("child_admin", role="admin", parent=superadmin)
    managed_path_factory("config-root", allow_view=True, allow_edit=True)
    grant_action(child, "commands.execute")
    with app.app_context():
        db_path = ManagedPath.query.one().absolute_path
        grant = PermissionGrant(
            user_id=child.id,
            scope_type="path",
            scope_value=db_path,
            capability="upload",
            effect="deny",
        )
        from app.extensions import db

        db.session.add(grant)
        db.session.commit()

    login("root_owner")
    response = client.get(f"/users/{child.id}")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Grant or deny actions" in page
    assert "Effective file access" in page
    assert "commands.execute" in page


def test_settings_server_root_sync_creates_managed_entries(app, client, user_factory, login, tmp_path: Path):
    user_factory("root_sync", role="superadmin")
    server_root = tmp_path / "minecraft-server"
    (server_root / "config").mkdir(parents=True)
    (server_root / "mods").mkdir()
    (server_root / "logs").mkdir()
    (server_root / "server.properties").write_text(
        "enable-rcon=true\nrcon.port=25570\nrcon.password=secret-pass\n",
        encoding="utf-8",
    )
    (server_root / "run.sh").write_text("#!/usr/bin/env bash\necho running\n", encoding="utf-8")

    login("root_sync")
    response = client.post(
        "/settings/",
        data={
            "system-server_root": str(server_root),
            "system-rcon_host": "127.0.0.1",
            "system-rcon_port": "25575",
            "system-rcon_password": "",
            "system-pending_upload_dir": str(tmp_path / "pending"),
            "system-backup_dir": str(tmp_path / "backups"),
            "system-submit": "1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    with app.app_context():
        assert ManagedPath.query.filter_by(label="Auto: Server root").one().absolute_path == str(
            server_root.resolve()
        )
        assert ManagedPath.query.filter_by(label="Auto: Mods").one().absolute_path == str(
            (server_root / "mods").resolve()
        )
        assert ManagedAction.query.filter_by(key="server.start").one().working_directory == str(
            server_root.resolve()
        )


def test_settings_page_shows_synced_paths_summary(app, client, user_factory, managed_path_factory, login):
    user_factory("root_settings", role="superadmin")
    managed_path_factory("config-root", allow_view=True, allow_edit=True)

    login("root_settings")
    response = client.get("/settings/")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Managed paths" in page
    assert "Add managed path" not in page
    assert 'name="path-label"' not in page