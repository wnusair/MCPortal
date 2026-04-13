from __future__ import annotations

from datetime import UTC, datetime

from app.extensions import db
from app.models import PendingRequest, StagedUpload, User
from app.services.audit import write_audit
from app.services.files import write_text_file
from app.services.server_control import run_managed_action, send_minecraft_command
from app.services.uploads import promote_staged_upload


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def create_pending_request(
    request_type: str,
    target: str,
    payload: dict,
    requester: User,
    *,
    target_name: str | None = None,
) -> PendingRequest:
    pending_request = PendingRequest(
        requester_id=requester.id,
        request_type=request_type,
        target=target,
        target_name=target_name or target,
        payload_json=payload,
    )
    db.session.add(pending_request)
    db.session.commit()
    write_audit(
        "requests.submitted",
        request_type,
        target_name or target,
        actor=requester,
        details={"payload": payload},
    )
    return pending_request


def review_pending_request(
    pending_request: PendingRequest,
    reviewer: User,
    *,
    approve: bool,
    review_note: str | None = None,
) -> PendingRequest:
    pending_request.reviewer_id = reviewer.id
    pending_request.reviewed_at = utcnow()
    pending_request.review_note = review_note or None

    if not approve:
        pending_request.status = "rejected"
        db.session.commit()
        write_audit(
            "requests.rejected",
            pending_request.request_type,
            pending_request.target_name or pending_request.target,
            actor=reviewer,
        )
        return pending_request

    try:
        if pending_request.request_type == "command":
            output = send_minecraft_command(pending_request.payload_json["command"])
            pending_request.payload_json = {**pending_request.payload_json, "result": output}
        elif pending_request.request_type == "file_edit":
            write_text_file(pending_request.target, pending_request.payload_json["content"])
        elif pending_request.request_type == "mod_upload":
            staged_upload = db.session.get(
                StagedUpload,
                int(pending_request.payload_json["staged_upload_id"]),
            )
            if staged_upload is None:
                raise ValueError("The staged upload could not be found.")
            promote_staged_upload(staged_upload)
        elif pending_request.request_type == "managed_action":
            pending_request.payload_json = {
                **pending_request.payload_json,
                "result": run_managed_action(pending_request.payload_json["action_key"]),
            }
        else:
            raise ValueError("Unsupported request type.")

        pending_request.status = "executed"
        pending_request.executed_at = utcnow()
        db.session.commit()
        write_audit(
            "requests.executed",
            pending_request.request_type,
            pending_request.target_name or pending_request.target,
            actor=reviewer,
        )
    except Exception as exc:
        pending_request.status = "failed"
        pending_request.error_message = str(exc)
        db.session.commit()
        write_audit(
            "requests.failed",
            pending_request.request_type,
            pending_request.target_name or pending_request.target,
            actor=reviewer,
            status="error",
            details={"error": str(exc)},
        )
        raise

    return pending_request