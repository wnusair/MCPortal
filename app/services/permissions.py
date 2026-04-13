from __future__ import annotations

from pathlib import Path

from app.models import ManagedAction, ManagedPath, PermissionGrant, ROLE_PRECEDENCE, User


BASE_ACTIONS = {
    "viewer": {
        "dashboard.view",
        "files.view",
        "commands.view",
        "mods.view",
        "auth.change_password",
        "requests.create",
    },
    "operator": {
        "dashboard.view",
        "files.view",
        "commands.view",
        "mods.view",
        "auth.change_password",
        "requests.create",
        "files.request_edit",
        "commands.request",
        "mods.request_upload",
    },
    "admin": {
        "dashboard.view",
        "files.view",
        "commands.view",
        "mods.view",
        "auth.change_password",
        "requests.create",
        "files.request_edit",
        "commands.request",
        "mods.request_upload",
        "users.view",
    },
}

ADMIN_ACTIONS = {
    "approvals.review",
    "audit.view",
    "commands.execute",
    "server.actions.run",
    "settings.manage",
    "users.create_underling",
    "users.manage_permissions",
}


def normalize_path(value: str) -> str:
    return str(Path(value).expanduser().resolve())


def _best_action_grant(user: User, action_key: str) -> PermissionGrant | None:
    matches: list[PermissionGrant] = []
    for grant in user.permission_grants.filter_by(scope_type="action", capability="access").all():
        if grant.scope_value == action_key:
            matches.append(grant)
        elif grant.scope_value.endswith("*") and action_key.startswith(grant.scope_value[:-1]):
            matches.append(grant)
    return max(matches, key=lambda grant: len(grant.scope_value), default=None)


def has_action_permission(user: User, action_key: str) -> bool:
    if not user or not user.is_active_account:
        return False
    if user.is_superadmin:
        return True

    grant = _best_action_grant(user, action_key)
    if grant is not None:
        return grant.effect == "allow"

    return action_key in BASE_ACTIONS.get(user.role, set())


def list_known_action_keys() -> list[str]:
    known_actions = set(ADMIN_ACTIONS)
    for action_group in BASE_ACTIONS.values():
        known_actions.update(action_group)
    for managed_action in ManagedAction.query.order_by(ManagedAction.key.asc()).all():
        known_actions.add(f"server.actions.{managed_action.key}")
    return sorted(known_actions)


def describe_action_permission(user: User, action_key: str) -> dict[str, str | bool]:
    if user.is_superadmin:
        return {"key": action_key, "allowed": True, "source": "superadmin"}

    grant = _best_action_grant(user, action_key)
    if grant is not None:
        return {
            "key": action_key,
            "allowed": grant.effect == "allow",
            "source": f"explicit {grant.effect}",
        }

    if action_key in BASE_ACTIONS.get(user.role, set()):
        return {"key": action_key, "allowed": True, "source": f"role: {user.role}"}

    return {"key": action_key, "allowed": False, "source": "not granted"}


def summarize_action_permissions(user: User) -> list[dict[str, str | bool]]:
    return [describe_action_permission(user, action_key) for action_key in list_known_action_keys()]


def _best_path_grant(user: User, absolute_path: str, capability: str) -> PermissionGrant | None:
    normalized_path = normalize_path(absolute_path)
    matches: list[PermissionGrant] = []
    for grant in user.permission_grants.filter_by(scope_type="path", capability=capability).all():
        candidate = normalize_path(grant.scope_value)
        if normalized_path == candidate or normalized_path.startswith(f"{candidate}/"):
            matches.append(grant)
    return max(matches, key=lambda grant: len(grant.scope_value), default=None)


def get_managed_root(absolute_path: str) -> ManagedPath | None:
    normalized_path = normalize_path(absolute_path)
    candidates = []
    for managed_path in ManagedPath.query.all():
        candidate = normalize_path(managed_path.absolute_path)
        if normalized_path == candidate or normalized_path.startswith(f"{candidate}/"):
            candidates.append(managed_path)
    return max(candidates, key=lambda item: len(item.absolute_path), default=None)


def has_path_capability(user: User, absolute_path: str, capability: str) -> bool:
    if not user or not user.is_active_account:
        return False
    if user.is_superadmin:
        return True

    managed_root = get_managed_root(absolute_path)
    if managed_root is None:
        return False

    grant = _best_path_grant(user, absolute_path, capability)
    if grant is not None:
        return grant.effect == "allow"

    if capability == "view":
        return managed_root.allow_view
    if capability == "edit":
        return managed_root.allow_edit and user.role in {"operator", "admin"}
    if capability == "upload":
        return managed_root.allow_upload and user.role in {"operator", "admin"}
    return False


def summarize_path_permissions(user: User) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for managed_path in ManagedPath.query.order_by(ManagedPath.label.asc()).all():
        summaries.append(
            {
                "label": managed_path.label,
                "path": managed_path.absolute_path,
                "path_type": managed_path.path_type,
                "view": has_path_capability(user, managed_path.absolute_path, "view"),
                "edit": has_path_capability(user, managed_path.absolute_path, "edit"),
                "upload": has_path_capability(user, managed_path.absolute_path, "upload"),
            }
        )
    return summaries


def can_create_underling(actor: User, requested_role: str) -> bool:
    if actor.is_superadmin:
        return True
    if not has_action_permission(actor, "users.create_underling"):
        return False
    return ROLE_PRECEDENCE.get(actor.role, 0) >= ROLE_PRECEDENCE.get(requested_role, 0)


def can_manage_user(actor: User, target: User) -> bool:
    if actor.is_superadmin:
        return True
    if actor.id == target.id:
        return False
    return has_action_permission(actor, "users.manage_permissions") and target.parent_id == actor.id
