from __future__ import annotations

import mimetypes
import shutil
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from flask import current_app

from app.services.permissions import get_managed_root, normalize_path
from app.services.system_settings import get_setting


TEXT_PREVIEW_BYTE_LIMIT = 512 * 1024
ARCHIVE_PREVIEW_LIMIT = 250
TEXT_PREVIEW_EXTENSIONS = {
    ".cfg",
    ".conf",
    ".csv",
    ".env",
    ".ini",
    ".json",
    ".json5",
    ".log",
    ".md",
    ".properties",
    ".sh",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
ARCHIVE_SUFFIX_GROUPS = (
    (".tar",),
    (".tar", ".gz"),
    (".tar", ".bz2"),
    (".tar", ".xz"),
    (".tgz",),
    (".tbz2",),
    (".txz",),
)
TEXT_MIME_TYPES = {
    "application/javascript",
    "application/json",
    "application/xml",
    "application/x-sh",
}


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


def _format_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%d %H:%M UTC")


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"

    value = float(size)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"

    return f"{size} B"


def _matches_suffix_group(path: Path, suffix_group: tuple[str, ...]) -> bool:
    suffixes = tuple(part.lower() for part in path.suffixes)
    return suffixes[-len(suffix_group) :] == suffix_group


def is_archive_file(path: Path) -> bool:
    return any(_matches_suffix_group(path, suffix_group) for suffix_group in ARCHIVE_SUFFIX_GROUPS)


def _is_previewable_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_PREVIEW_EXTENSIONS:
        return True

    mime_type, encoding = mimetypes.guess_type(path.name)
    if encoding:
        return False
    if mime_type is None:
        return False
    return mime_type.startswith("text/") or mime_type in TEXT_MIME_TYPES


def is_editable_text_file(absolute_path: str) -> bool:
    path = Path(normalize_path(absolute_path))
    return path.suffix.lower() in current_app.config["ALLOWED_TEXT_EXTENSIONS"] and path.suffix.lower() != ".log"


def _entry_type_label(path: Path) -> str:
    if path.is_dir():
        return "Folder"
    if is_archive_file(path):
        return "Archive"
    if path.suffix.lower() == ".log":
        return "Log"
    if _is_previewable_text_file(path):
        return "Text"
    return "File"


def describe_path(absolute_path: str) -> dict[str, str | bool]:
    path = Path(normalize_path(absolute_path))
    if not path.exists():
        raise FileAccessError("Path does not exist.")

    stat_result = path.stat()
    mime_type, _ = mimetypes.guess_type(path.name)
    preview_mode = "raw"
    if path.is_dir():
        preview_mode = "directory"
    elif is_archive_file(path):
        preview_mode = "archive"
    elif _is_previewable_text_file(path) or is_editable_text_file(str(path)):
        preview_mode = "text"

    return {
        "entry_type": _entry_type_label(path),
        "mime_type": mime_type or "application/octet-stream",
        "modified_at": _format_timestamp(stat_result.st_mtime),
        "preview_mode": preview_mode,
        "size_display": "--" if path.is_dir() else _format_size(stat_result.st_size),
        "supports_edit": path.is_file() and is_editable_text_file(str(path)),
    }


def _directory_entry(entry: Path, root: Path) -> dict[str, str | bool]:
    details = describe_path(str(entry))
    return {
        "entry_type": details["entry_type"],
        "is_dir": entry.is_dir(),
        "modified_at": details["modified_at"],
        "name": entry.name,
        "relative_path": str(entry.relative_to(root)),
        "size_display": details["size_display"],
    }


def list_directory(root_path: str, subpath: str = "") -> list[dict[str, str | bool]]:
    target = resolve_safe_path(root_path, subpath)
    if not target.exists() or not target.is_dir():
        raise FileAccessError("Directory does not exist.")

    root = Path(root_path).resolve()
    entries = []
    for entry in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        entries.append(_directory_entry(entry, root))
    return entries


def read_text_file(absolute_path: str) -> str:
    path = Path(normalize_path(absolute_path))
    if not path.exists() or not path.is_file():
        raise FileAccessError("File does not exist.")
    if not is_editable_text_file(str(path)):
        raise FileAccessError("This file type cannot be edited through the web UI.")
    return path.read_text(encoding="utf-8")


def read_text_preview(absolute_path: str) -> str:
    path = Path(normalize_path(absolute_path))
    if not path.exists() or not path.is_file():
        raise FileAccessError("File does not exist.")
    if is_archive_file(path) or not (_is_previewable_text_file(path) or is_editable_text_file(str(path))):
        raise FileAccessError("This file type cannot be previewed in the browser.")

    with path.open("rb") as handle:
        data = handle.read(TEXT_PREVIEW_BYTE_LIMIT + 1)

    truncated = len(data) > TEXT_PREVIEW_BYTE_LIMIT
    preview = data[:TEXT_PREVIEW_BYTE_LIMIT].decode("utf-8", errors="replace")
    if truncated:
        preview += "\n\n[Preview truncated after 512 KB]"
    return preview


def list_archive_members(absolute_path: str) -> list[dict[str, str]]:
    path = Path(normalize_path(absolute_path))
    if not path.exists() or not path.is_file():
        raise FileAccessError("File does not exist.")
    if not is_archive_file(path):
        raise FileAccessError("This file is not a supported archive.")

    try:
        with tarfile.open(path, mode="r:*") as archive:
            members: list[dict[str, str]] = []
            for index, member in enumerate(archive):
                if index >= ARCHIVE_PREVIEW_LIMIT:
                    break
                members.append(
                    {
                        "entry_type": "Directory" if member.isdir() else "File",
                        "name": member.name,
                        "size_display": "--" if member.isdir() else _format_size(member.size),
                    }
                )
            return members
    except tarfile.TarError as exc:
        raise FileAccessError("This archive could not be read.") from exc


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
