from __future__ import annotations

from flask import current_app

from app.extensions import db
from app.models import SystemSetting


def get_setting(key: str, default: str | None = None) -> str | None:
    setting = SystemSetting.query.filter_by(key=key).first()
    if setting:
        return setting.value
    return current_app.config.get(key.upper(), default)


def set_setting(key: str, value: str) -> None:
    setting = SystemSetting.query.filter_by(key=key).first()
    if setting is None:
        setting = SystemSetting(key=key, value=value)
        db.session.add(setting)
    else:
        setting.value = value
    db.session.commit()
