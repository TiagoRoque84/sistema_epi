"""Conversão dos horários gravados em UTC para o fuso local.

O banco guarda tudo em UTC, e isso está certo: o valor não muda quando entra ou
sai o horário de verão, nem quando o servidor é movido. O que faltava era a
outra metade — ninguém lê um comprovante em UTC. Toda exibição de data e hora
passa por aqui.

O fuso vem de `TIMEZONE` no `.env`, com `America/Sao_Paulo` como padrão.

O Windows não possui a base de fusos do sistema; quem a fornece é o pacote
`tzdata`, declarado em requirements.txt. Sem ele a conversão não teria como
acontecer, então a ausência é registrada em log em vez de passar despercebida.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app, has_app_context


DEFAULT_TIMEZONE = "America/Sao_Paulo"

_zones: dict[str, tzinfo] = {}
_warned: set[str] = set()


def zone_name() -> str:
    if has_app_context():
        return current_app.config.get("TIMEZONE") or DEFAULT_TIMEZONE
    return DEFAULT_TIMEZONE


def local_zone() -> tzinfo:
    name = zone_name()
    cached = _zones.get(name)
    if cached is not None:
        return cached

    try:
        resolved: tzinfo = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        if name not in _warned:
            logging.getLogger(__name__).error(
                "Fuso '%s' não encontrado. Os horários continuarão em UTC. "
                "Instale o pacote tzdata: .venv\\Scripts\\python.exe -m pip install tzdata",
                name,
            )
            _warned.add(name)
        resolved = timezone.utc

    _zones[name] = resolved
    return resolved


def to_local(value: datetime | None) -> datetime | None:
    """Converte um instante para o fuso local. Datas ingênuas são tratadas como UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(local_zone())


def local_now() -> datetime:
    return datetime.now(local_zone())


def local_today() -> date:
    return local_now().date()


def format_datetime(value: datetime | None) -> str:
    converted = to_local(value)
    return converted.strftime("%d/%m/%Y %H:%M") if converted else "—"


def format_date(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        converted = to_local(value)
        return converted.strftime("%d/%m/%Y") if converted else "—"
    return value.strftime("%d/%m/%Y")
