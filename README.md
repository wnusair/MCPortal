# MCPortal

MCPortal is a Flask control panel for managing a Fabric Minecraft server from the web without exposing arbitrary shell access. It provides server-rendered administration pages, staged approval flows, audit logging, path-level file permissions, moderated mod uploads, and RCON-based Minecraft command execution.

## Current scope

- Same-host deployment only for the first version
- Username/password authentication with password changes
- Concurrent session limits and login rate limiting
- Parent-child user hierarchy with explicit permission grants
- Managed file roots with read, edit, and upload capabilities
- Pending approval queue for unauthorized commands, file edits, and mod uploads
- Managed lifecycle buttons backed by fixed executable paths
- Append-only audit log for authentication, permission, and content-change events

## Safety model

- Normal server commands go through Minecraft RCON only
- Lifecycle buttons run only superadmin-configured managed actions
- No freeform shell command execution is exposed in the UI
- File browsing is restricted to managed root paths
- Path traversal is rejected server-side
- CSRF protection is enabled outside tests
- SQLAlchemy ORM is used for database access rather than raw SQL

## Local setup

1. Create a virtual environment.
2. Install the project with development tools.
3. Copy `.env.example` to `.env` and set a real `SECRET_KEY`.
4. Run the Flask app.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
flask --app run.py run --debug
```

Open the app, visit `/bootstrap`, and create the first superadmin account.

The sample `DATABASE_URL=sqlite:///mcportal.db` stores the SQLite file under the Flask `instance/` directory.

## First configuration steps

1. Go to Settings.
2. Set the RCON host, port, and password.
3. Add one or more managed paths for config files and mods.
4. Add managed lifecycle actions such as `server.start`, `server.stop`, and `server.restart` using absolute executable paths.
5. Create underlings and permission grants.

## Running tests

```bash
pytest
```

## Useful action keys

- `commands.execute`
- `server.actions.run`
- `server.actions.server.start`
- `users.create_underling`
- `users.manage_permissions`
- `approvals.review`
- `settings.manage`
- `audit.view`

Action grants can also use a wildcard suffix, such as `server.actions.*`.

## Managed path permissions

- `view`
- `edit`
- `upload`

Path grants apply by prefix match on absolute paths.

## Notes

- SQLite is used for the MVP and can be swapped later through SQLAlchemy.
- Pending uploads and file backups default to the `instance/` directory unless overridden.
- The initial UI is intentionally server-rendered and centered around safe operations first.
# MCPortal
