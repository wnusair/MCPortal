from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from flask import current_app

from app.services.permissions import get_managed_root, normalize_path
from app.services.system_settings import get_setting


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class FileAccessError(ValueError):
    pass


def resolve_safe_path(root_path: str, subpath: str = "") -> Path:
    base = Path(root_path).expanduser().resolve()
    target = (base / subpath).resolve()
    if target != base and base not in target.parents:
        raise FileAccessError("Path traversal is not allowed.")
    return target


def list_directory(root_path: str, subpath: str = "") -> list[dict[str, str | bool]]:
    target = resolve_safe_path(root_path, subpath)
    if not target.exists() or not target.is_dir():
        raise FileAccessError("Directory does not exist.")

    entries = []
    for entry in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        entries.append(
            {
                "name": entry.name,
                "relative_path": str(entry.relative_to(Path(root_path).resolve())),
                "is_dir": entry.is_dir(),
            }
        )
    return entries


def read_text_file(absolute_path: str) -> str:
    path = Path(normalize_path(absolute_path))
    if not path.exists() or not path.is_file():
        raise FileAccessError("File does not exist.")
    if path.suffix.lower() not in current_app.config["ALLOWED_TEXT_EXTENSIONS"]:
        raise FileAccessError("This file type cannot be edited through the web UI.")
    return path.read_text(encoding="utf-8")


def write_text_file(absolute_path: str, content: str) -> Path:
    target = Path(normalize_path(absolute_path))
    managed_root = get_managed_root(str(target))
    if managed_root is None:
        raise FileAccessError("The target path is not managed by MCPortal.")

    backup_dir = Path(get_setting("backup_dir", current_app.config["BACKUP_DIR"])).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = utcnow().strftime("%Y%m%d%H%M%S")
    backup_name = f"{timestamp}_{target.name}"
    backup_path = backup_dir / backup_name
    if target.exists():
        shutil.copy2(target, backup_path)

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(f"{target.suffix}.mcportal.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(target)
    return backup_path
