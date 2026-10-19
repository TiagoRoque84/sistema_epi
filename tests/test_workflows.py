from __future__ import annotations

from pathlib import Path

from app.email_service import process_pending_emails
from app.extensions import db
from app.models import Delivery, EmailOutbox, Solicitation, StockMovement, StockVariant


def test_all_main_pages_render(client, login):
    assert login().status_code == 302
    for url in ["/", "/colaboradores", "/estoque", "/estoque/reposicao", "/solicitacoes", "/entregas", "/relatorios", "/administracao"]:
        response = client.get(url)
        assert response.status_code == 200, url


def test_partial_signed_delivery_alert_pdf_and_reversal(app, client, login, signature_data_url):
    login()
    response = client.post(
        "/solicitacoes/nova",
        data={"employee_id": "1", "priority": "normal", "variant_id": ["1"], "quantity": ["2"]},
        follow_redirects=False,
    )
    assert response.status_code == 302

    response = client.post(
        "/entregas/nova",
        data={"employee_id": "1", "solicitation_id": "1", "variant_id": ["1"], "quantity": ["1"], "signature_data": signature_data_url},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        delivery = db.session.get(Delivery, 1)
        solicitation = db.session.get(Solicitation, 1)
        variant = db.session.get(StockVariant, 1)
        assert delivery.status == "completed"
        assert solicitation.status == "partial"
        assert variant.current_quantity == 4
        assert delivery.retention_until.year == delivery.delivered_at.year + 5
        assert (Path(app.config["DATA_DIR"]) / delivery.signature_path).is_file()
        assert (Path(app.config["DATA_DIR"]) / delivery.receipt_pdf_path).read_bytes().startswith(b"%PDF")
        queued = db.session.scalar(db.select(EmailOutbox))
        assert queued and queued.status == "pending"
        sent, failed = process_pending_emails()
        assert (sent, failed) == (1, 0)

    response = client.post("/entregas/1/estornar", data={"reason": "Lançamento de teste incorreto"})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Delivery, 1).status == "reversed"
        assert db.session.get(Solicitation, 1).status == "pending"
        assert db.session.get(StockVariant, 1).current_quantity == 5
        assert db.session.scalar(db.select(db.func.count()).select_from(StockMovement)) == 2


def test_blank_signature_is_rejected(app, client, login):
    login()
    response = client.post("/entregas/nova", data={"employee_id": "1", "variant_id": ["1"], "quantity": ["1"], "signature_data": ""})
    assert response.status_code == 200
    assert "Assinatura inválida".encode("utf-8") in response.data
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(Delivery)) == 0


def test_negative_stock_is_allowed(app, client, login, signature_data_url):
    login()
    with app.app_context():
        db.session.get(StockVariant, 1).current_quantity = 0
        db.session.commit()
    response = client.post("/entregas/nova", data={"employee_id": "1", "variant_id": ["1"], "quantity": ["3"], "signature_data": signature_data_url})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(StockVariant, 1).current_quantity == -3


def test_viewer_cannot_operate(client, login):
    login("consulta", "senha-segura-456")
    assert client.get("/estoque").status_code == 200
    assert client.post("/estoque/1/movimentar", data={"movement_type": "entry", "quantity": "1", "reason": "teste"}).status_code == 403
