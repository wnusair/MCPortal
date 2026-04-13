from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.extensions import db
from app.models import ManagedAction, ManagedPath


@dataclass(frozen=True)
class ManagedPathSpec:
    label: str
    relative_path: str | None
    path_type: str
    allow_view: bool
    allow_edit: bool
    allow_upload: bool
    create_when_missing: bool = False


@dataclass(frozen=True)
class ManagedActionSpec:
    key: str
    label: str
    candidates: tuple[str, ...]


@dataclass
class ServerSyncResult:
    created_paths: int = 0
    updated_paths: int = 0
    deleted_paths: int = 0
    created_actions: int = 0
    imported_rcon_port: str | None = None
    imported_rcon_password: str | None = None


AUTO_PATH_SPECS = (
    ManagedPathSpec("Auto: Server root", None, "data", True, False, False, create_when_missing=True),
    ManagedPathSpec("Auto: Config", "config", "config", True, True, False),
    ManagedPathSpec("Auto: Mods", "mods", "mods", True, False, True, create_when_missing=True),
    ManagedPathSpec("Auto: Logs", "logs", "data", True, False, False),
    ManagedPathSpec("Auto: Crash reports", "crash-reports", "data", True, False, False),
    ManagedPathSpec("Auto: World", "world", "data", True, False, False),
    ManagedPathSpec("Auto: Server properties", "server.properties", "config", True, True, False),
    ManagedPathSpec("Auto: EULA", "eula.txt", "config", True, True, False),
    ManagedPathSpec("Auto: Operators", "ops.json", "config", True, True, False),
    ManagedPathSpec("Auto: Whitelist", "whitelist.json", "config", True, True, False),
    ManagedPathSpec("Auto: Banned players", "banned-players.json", "config", True, True, False),
    ManagedPathSpec("Auto: Banned IPs", "banned-ips.json", "config", True, True, False),
    ManagedPathSpec("Auto: User cache", "usercache.json", "config", True, False, False),
    ManagedPathSpec(
        "Auto: Fabric launcher settings",
        "fabric-server-launcher.properties",
        "config",
        True,
        True,
        False,
    ),
)

AUTO_ACTION_SPECS = (
    ManagedActionSpec("server.start", "Start server", ("run.sh", "start.sh", "server-start.sh")),
    ManagedActionSpec("server.stop", "Stop server", ("stop.sh", "server-stop.sh")),
    ManagedActionSpec("server.restart", "Restart server", ("restart.sh", "server-restart.sh")),
)


def _resolve_spec_path(root: Path, spec: ManagedPathSpec) -> Path:
    if spec.relative_path is None:
        return root
    return root / spec.relative_path


def _upsert_auto_path(spec: ManagedPathSpec, target: Path, result: ServerSyncResult) -> None:
    managed_path = ManagedPath.query.filter_by(label=spec.label).first()
    resolved_path = str(target.resolve())
    if managed_path is None:
        managed_path = ManagedPath(
            label=spec.label,
            absolute_path=resolved_path,
            path_type=spec.path_type,
            allow_view=spec.allow_view,
            allow_edit=spec.allow_edit,
            allow_upload=spec.allow_upload,
        )
        db.session.add(managed_path)
        result.created_paths += 1
        return

    changed = (
        managed_path.absolute_path != resolved_path
        or managed_path.path_type != spec.path_type
        or managed_path.allow_view != spec.allow_view
        or managed_path.allow_edit != spec.allow_edit
        or managed_path.allow_upload != spec.allow_upload
    )
    managed_path.absolute_path = resolved_path
    managed_path.path_type = spec.path_type
    managed_path.allow_view = spec.allow_view
    managed_path.allow_edit = spec.allow_edit
    managed_path.allow_upload = spec.allow_upload
    if changed:
        result.updated_paths += 1


def _delete_stale_auto_paths(active_labels: set[str], result: ServerSyncResult) -> None:
    for managed_path in ManagedPath.query.filter(ManagedPath.label.like("Auto:%")).all():
        if managed_path.label not in active_labels:
            db.session.delete(managed_path)
            result.deleted_paths += 1


def _maybe_create_action(root: Path, spec: ManagedActionSpec, result: ServerSyncResult) -> None:
    if ManagedAction.query.filter_by(key=spec.key).first() is not None:
        return

    script = next((root / candidate for candidate in spec.candidates if (root / candidate).exists()), None)
    if script is None:
        return

    db.session.add(
        ManagedAction(
            key=spec.key,
            label=spec.label,
            executable_path="/usr/bin/env",
            arguments_json=json.dumps(["bash", str(script.resolve())]),
            working_directory=str(root),
            enabled=True,
        )
    )
    result.created_actions += 1


def _read_server_properties(server_root: Path) -> dict[str, str]:
    properties_path = server_root / "server.properties"
    if not properties_path.exists() or not properties_path.is_file():
        return {}

    properties: dict[str, str] = {}
    for raw_line in properties_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key.strip()] = value.strip()
    return properties


def sync_server_root(server_root: str) -> ServerSyncResult:
    root = Path(server_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("Choose an existing server directory.")

    result = ServerSyncResult()
    active_labels: set[str] = set()
    for spec in AUTO_PATH_SPECS:
        target = _resolve_spec_path(root, spec)
        if not target.exists() and not spec.create_when_missing:
            continue
        _upsert_auto_path(spec, target, result)
        active_labels.add(spec.label)

    _delete_stale_auto_paths(active_labels, result)

    for spec in AUTO_ACTION_SPECS:
        _maybe_create_action(root, spec, result)

    properties = _read_server_properties(root)
    if properties.get("enable-rcon", "false").lower() == "true":
        if properties.get("rcon.port"):
            result.imported_rcon_port = properties["rcon.port"]
        if properties.get("rcon.password"):
            result.imported_rcon_password = properties["rcon.password"]

    db.session.commit()
    return result