from __future__ import annotations

from typing import Any

from flask import has_request_context, request
from flask_login import current_user
from sqlalchemy import inspect as sa_inspect

from app.extensions import db
from app.models import AuditLog


SENSITIVE_FIELDS = {"password_hash", "signature_path", "signature_sha256"}


def model_snapshot(instance) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for column in sa_inspect(instance.__class__).columns:
        if column.key in SENSITIVE_FIELDS:
            continue
        value = getattr(instance, column.key)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        snapshot[column.key] = value
    return snapshot


def record_audit(
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    log = AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before_json=before,
        after_json=after,
        ip_address=request.remote_addr if has_request_context() else None,
        user_agent=(request.user_agent.string[:500] if has_request_context() else None),
    )
    db.session.add(log)
    return log
