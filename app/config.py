from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    PRODUCTION_MODE = os.getenv("PRODUCTION_MODE", "0") == "1"
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-before-production")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{(BASE_DIR / 'instance' / 'epi.db').as_posix()}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    WTF_CSRF_TIME_LIMIT = 8 * 60 * 60
    MAX_CONTENT_LENGTH = 3 * 1024 * 1024

    ALLOW_NEGATIVE_STOCK = os.getenv("ALLOW_NEGATIVE_STOCK", "1") == "1"
    RECEIPT_RETENTION_YEARS = int(os.getenv("RECEIPT_RETENTION_YEARS", "5"))

    # Os horários são gravados em UTC e convertidos para este fuso na exibição.
    TIMEZONE = os.getenv("TIMEZONE", "America/Sao_Paulo")

    DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "instance"))
    SIGNATURE_DIR = DATA_DIR / "signatures"
    RECEIPT_DIR = DATA_DIR / "receipts"

    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1") == "1"
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", SMTP_USERNAME)
    APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8080")
    DEFAULT_ALERT_EMAIL = os.getenv(
        "DEFAULT_ALERT_EMAIL", "alertas@example.invalid"
    )
    MAIL_SUPPRESS_SEND = os.getenv("MAIL_SUPPRESS_SEND", "0") == "1"


class TestConfig(Config):
    PRODUCTION_MODE = False
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite+pysqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    MAIL_SUPPRESS_SEND = True
    SESSION_COOKIE_SECURE = False
