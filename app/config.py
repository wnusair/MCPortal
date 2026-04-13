from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"

load_dotenv()


def _resolve_path(value: str | None, *, default: Path, relative_to: Path = BASE_DIR) -> str:
    path = Path(value) if value else default
    if not path.is_absolute():
        path = relative_to / path
    return str(path.resolve())


def _resolve_database_uri(value: str | None) -> str:
    if not value:
        return f"sqlite:///{(INSTANCE_DIR / 'mcportal.db').resolve()}"

    if value in {"sqlite://", "sqlite:///:memory:"}:
        return value

    sqlite_prefix = "sqlite:///"
    if value.startswith(sqlite_prefix) and not value.startswith("sqlite:////"):
        raw_path = value[len(sqlite_prefix) :]
        if raw_path == ":memory:":
            return value

        db_path = Path(raw_path)
        if not db_path.is_absolute():
            if db_path.parts[:1] == ("instance",):
                db_path = INSTANCE_DIR.joinpath(*db_path.parts[1:])
            else:
                db_path = INSTANCE_DIR / db_path

        return f"sqlite:///{db_path.resolve()}"

    return value


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
    SQLALCHEMY_DATABASE_URI = _resolve_database_uri(os.getenv("DATABASE_URL"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True
    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "200/hour;50/minute")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.getenv("SESSION_LIFETIME_HOURS", "12")))
    MAX_CONCURRENT_SESSIONS = int(os.getenv("MAX_CONCURRENT_SESSIONS", "3"))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(32 * 1024 * 1024)))
    WTF_CSRF_TIME_LIMIT = None
    BACKUP_DIR = _resolve_path(os.getenv("BACKUP_DIR"), default=INSTANCE_DIR / "backups")
    PENDING_UPLOAD_DIR = _resolve_path(
        os.getenv("PENDING_UPLOAD_DIR"),
        default=INSTANCE_DIR / "pending_uploads",
    )
    RCON_HOST = os.getenv("RCON_HOST", "127.0.0.1")
    RCON_PORT = int(os.getenv("RCON_PORT", "25575"))
    RCON_PASSWORD = os.getenv("RCON_PASSWORD", "")
    RCON_TIMEOUT = int(os.getenv("RCON_TIMEOUT", "5"))
    ALLOWED_UPLOAD_EXTENSIONS = {"jar"}
    ALLOWED_TEXT_EXTENSIONS = {
        ".cfg",
        ".conf",
        ".json",
        ".json5",
        ".properties",
        ".toml",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
    CONTENT_SECURITY_POLICY = {
        "default-src": ["'self'"],
        "style-src": ["'self'"],
        "script-src": ["'self'"],
        "img-src": ["'self'", "data:"],
        "font-src": ["'self'"],
        "connect-src": ["'self'"],
    }


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SERVER_NAME = "localhost"
