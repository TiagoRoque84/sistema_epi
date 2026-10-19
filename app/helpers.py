from __future__ import annotations

from datetime import date

from flask import abort, request


def clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def integer(value: str | None, *, field: str, minimum: int | None = None) -> int:
    try:
        parsed = int((value or "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}: informe um número inteiro válido.") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field}: o valor mínimo é {minimum}.")
    return parsed


def optional_integer(value: str | None, *, field: str, minimum: int | None = None) -> int | None:
    if not (value or "").strip():
        return None
    return integer(value, field=field, minimum=minimum)


def optional_date(value: str | None, *, field: str) -> date | None:
    if not (value or "").strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field}: informe uma data válida.") from exc


def require_text(value: str | None, *, field: str, max_length: int = 255) -> str:
    parsed = (value or "").strip()
    if not parsed:
        raise ValueError(f"{field} é obrigatório.")
    if len(parsed) > max_length:
        raise ValueError(f"{field} deve possuir no máximo {max_length} caracteres.")
    return parsed


def request_ip() -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    return (forwarded.split(",", 1)[0].strip() if forwarded else request.remote_addr) or None


def get_or_404(model, object_id: int):
    from app.extensions import db

    item = db.session.get(model, object_id)
    if item is None:
        abort(404)
    return item
