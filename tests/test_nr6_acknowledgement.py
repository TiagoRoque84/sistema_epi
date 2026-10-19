from pathlib import Path

import pytest

from app.extensions import db
from app.models import AppSetting, Delivery
from app.settings_service import (
    DEFAULT_ACKNOWLEDGEMENT,
    NR6_CLAUSE,
    NR6_CLAUSE_HEADING,
    acknowledgement_text,
    set_setting,
)


def test_default_term_includes_nr6_without_changing_settings(app):
    with app.app_context():
        assert acknowledgement_text() == f"{DEFAULT_ACKNOWLEDGEMENT}\n\n{NR6_CLAUSE}"
        assert db.session.get(AppSetting, "acknowledgement_text") is None


def test_custom_term_is_preserved_and_clause_is_not_duplicated(app):
    with app.app_context():
        custom = "Declaro o recebimento dos itens e das orientações da empresa."
        set_setting("acknowledgement_text", custom)
        db.session.commit()
        combined = acknowledgement_text()
        assert combined.startswith(custom)
        assert combined.count(NR6_CLAUSE_HEADING) == 1
        set_setting("acknowledgement_text", combined)
        db.session.commit()
        assert acknowledgement_text() == combined


@pytest.mark.parametrize("mode", ["digital", "paper"])
def test_nr6_is_snapshotted_for_both_signature_modes_and_old_receipt_is_preserved(
    app, client, login, signature_data_url, mode
):
    login()
    data = {"employee_id": "1", "variant_id": "1", "quantity": "1", "signature_mode": mode}
    if mode == "digital":
        data["signature_data"] = signature_data_url
    response = client.post("/entregas/nova", data=data)
    assert response.status_code == 302
    with app.app_context():
        delivery = db.session.get(Delivery, 1)
        accepted = delivery.acknowledgement_text
        assert NR6_CLAUSE in accepted
        receipt_path = Path(app.config["DATA_DIR"]) / delivery.receipt_pdf_path
        original_pdf = receipt_path.read_bytes()
        original_hash = delivery.receipt_sha256
    settings = client.get("/administracao/configuracoes")
    assert settings.status_code == 200
    assert b"nr-06-atualizada-2025-ii.pdf" in settings.data
    assert NR6_CLAUSE_HEADING.encode() in settings.data
    response = client.post("/administracao/configuracoes", data={
        "alert_email": "qa@example.test", "acknowledgement_text": "Termo revisado pela equipe.",
    })
    assert response.status_code == 302
    with app.app_context():
        delivery = db.session.get(Delivery, 1)
        assert delivery.acknowledgement_text == accepted
        assert delivery.receipt_sha256 == original_hash
        assert receipt_path.read_bytes() == original_pdf
        assert acknowledgement_text().startswith("Termo revisado pela equipe.")
        assert acknowledgement_text().count(NR6_CLAUSE_HEADING) == 1
