from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import StagedUpload, User
from app.services.system_settings import get_setting


class UploadError(ValueError):
    pass


def _allowed_extension(filename: str) -> bool:
    parts = filename.rsplit(".", 1)
    return len(parts) == 2 and parts[1].lower() in current_app.config["ALLOWED_UPLOAD_EXTENSIONS"]


def stage_upload(file_storage: FileStorage, destination_path: str, requester: User) -> StagedUpload:
    if not _allowed_extension(file_storage.filename or ""):
        raise UploadError("Only .jar uploads are allowed.")

    pending_dir = Path(
        get_setting("pending_upload_dir", current_app.config["PENDING_UPLOAD_DIR"])
    ).resolve()
    pending_dir.mkdir(parents=True, exist_ok=True)

    safe_name = secure_filename(file_storage.filename or "mod.jar")
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    stored_path = pending_dir / stored_name
    file_storage.save(stored_path)

    digest = hashlib.sha256(stored_path.read_bytes()).hexdigest()
    staged_upload = StagedUpload(
        requester_id=requester.id,
        original_filename=safe_name,
        stored_path=str(stored_path),
        destination_path=str(Path(destination_path).resolve()),
        checksum_sha256=digest,
        file_size=stored_path.stat().st_size,
    )
    db.session.add(staged_upload)
    db.session.commit()
    return staged_upload


def promote_staged_upload(staged_upload: StagedUpload) -> Path:
    source = Path(staged_upload.stored_path).resolve()
    if not source.exists():
        raise UploadError("The staged upload no longer exists.")

    destination_root = Path(staged_upload.destination_path).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    target = destination_root / staged_upload.original_filename
    shutil.move(str(source), target)
    staged_upload.status = "promoted"
    db.session.commit()
    return target
