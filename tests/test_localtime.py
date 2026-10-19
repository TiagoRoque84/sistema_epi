from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db
from app.localtime import format_date, format_datetime, to_local
from app.models import Delivery


def test_converte_utc_para_horario_de_brasilia(app):
    """O Brasil não adota mais horário de verão, então o deslocamento é fixo em -3."""
    with app.app_context():
        momento = datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)
        assert format_datetime(momento) == "30/09/2026 20:30"


def test_conversao_pode_mudar_o_dia(app):
    """Uma entrega às 21h no Brasil cai no dia seguinte em UTC; o usuário vê o dia certo."""
    with app.app_context():
        momento = datetime(2026, 10, 1, 0, 30, tzinfo=timezone.utc)
        convertido = to_local(momento)
        assert convertido.strftime("%d/%m/%Y %H:%M") == "30/09/2026 21:30"
        assert convertido.date().day == 30


def test_data_ingenua_e_tratada_como_utc(app):
    with app.app_context():
        assert format_datetime(datetime(2026, 9, 30, 23, 30)) == "30/09/2026 20:30"


def test_valores_vazios_e_datas_puras(app):
    with app.app_context():
        assert format_datetime(None) == "—"
        assert format_date(None) == "—"
        # Uma data sem hora não sofre conversão: não representa um instante.
        assert format_date(datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc).date()) == "30/09/2026"


def test_entrega_mostra_horario_local_na_tela(app, client, login, signature_data_url):
    login()
    response = client.post(
        "/entregas/nova",
        data={"employee_id": "1", "variant_id": ["1"], "quantity": ["1"], "signature_data": signature_data_url},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        delivery = db.session.get(Delivery, 1)
        # O instante é gravado em UTC; o SQLite dos testes o devolve sem fuso,
        # e to_local trata data ingênua como UTC, que é o caso aqui.
        bruto = delivery.delivered_at.strftime("%d/%m/%Y %H:%M")
        esperado = format_datetime(delivery.delivered_at)
        assert esperado != bruto, "a conversão para o fuso local não aconteceu"

    page = client.get("/entregas/1")
    assert page.status_code == 200
    assert esperado.encode("utf-8") in page.data
