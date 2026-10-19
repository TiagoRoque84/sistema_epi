from pathlib import Path

from app.extensions import db
from app.models import AuditLog, Delivery, Solicitation, StockMovement, StockVariant


def paper_form(**overrides):
    return {"employee_id": "1", "variant_id": ["1"], "quantity": ["1"], "signature_mode": "paper", **overrides}


def test_paper_delivery_receipt_history_audit_and_reversal(app, client, login):
    login()
    response = client.post("/entregas/nova", data=paper_form(), follow_redirects=True)
    assert response.status_code == 200
    assert "Sem assinatura digital".encode() in response.data
    assert b'src="/entregas/1/assinatura"' not in response.data
    with app.app_context():
        delivery = db.session.get(Delivery, 1)
        assert delivery.status == "completed"
        assert not delivery.has_digital_signature
        assert delivery.signature_path == delivery.signature_sha256 == ""
        assert db.session.get(StockVariant, 1).current_quantity == 4
        path = Path(app.config["DATA_DIR"]) / delivery.receipt_pdf_path
        assert path.read_bytes().startswith(b"%PDF")
        import hashlib
        assert delivery.receipt_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert not list(Path(app.config["SIGNATURE_DIR"]).rglob("*.png"))
        audit = db.session.scalar(db.select(AuditLog).where(AuditLog.entity_type == "Delivery"))
        assert audit.after_json["signature_mode"] == "paper"
    assert client.get("/entregas/1/comprovante").mimetype == "application/pdf"
    assert client.get("/entregas/1/assinatura").status_code == 302
    assert "No papel (sem digital)".encode() in client.get("/entregas").data
    assert "Assinatura no papel".encode() in client.get("/colaboradores/1").data
    assert client.post("/entregas/1/estornar", data={"reason": "Teste de devolução"}).status_code == 302
    with app.app_context():
        assert db.session.get(StockVariant, 1).current_quantity == 5
        assert db.session.get(Delivery, 1).status == "reversed"


def test_paper_delivery_partial_solicitation(app, client, login):
    login()
    client.post("/solicitacoes/nova", data={"employee_id": "1", "variant_id": ["1"], "quantity": ["2"]})
    assert client.post("/entregas/nova", data=paper_form(solicitation_id="1")).status_code == 302
    with app.app_context():
        assert db.session.get(Solicitation, 1).status == "partial"
        assert db.session.get(Solicitation, 1).items[0].quantity_delivered == 1


def test_invalid_mode_does_not_change_stock(app, client, login):
    login()
    response = client.post("/entregas/nova", data=paper_form(signature_mode="invalid"))
    assert response.status_code == 200
    assert "forma de assinatura válida".encode() in response.data
    with app.app_context():
        assert db.session.get(StockVariant, 1).current_quantity == 5
        assert db.session.scalar(db.select(db.func.count()).select_from(Delivery)) == 0


def test_paper_mode_ignores_signature_left_on_form(app, client, login, signature_data_url):
    login()
    assert client.post("/entregas/nova", data=paper_form(signature_data=signature_data_url)).status_code == 302
    with app.app_context():
        assert not db.session.get(Delivery, 1).has_digital_signature


def test_failed_paper_delivery_keeps_paper_option(app, client, login):
    login()
    response = client.post("/entregas/nova", data=paper_form(quantity=["0"]))
    assert response.status_code == 200
    assert b'data-paper-signature checked' in response.data
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(StockMovement)) == 0
        assert not list(Path(app.config["RECEIPT_DIR"]).rglob("*.pdf"))


def test_viewer_cannot_create_paper_delivery(client, login):
    login("consulta", "senha-segura-456")
    assert client.post("/entregas/nova", data=paper_form()).status_code == 403
