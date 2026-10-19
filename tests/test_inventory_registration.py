from app.extensions import db
from app.models import Category, Product, StockMovement, StockVariant
from sqlalchemy.exc import IntegrityError


def register(client, **fields):
    data = {"category": "Proteção da cabeça", "name": "Capacete", "active": "on"}
    data.update(fields)
    return client.post("/estoque/produtos/novo", data=data)


def test_new_product_with_optional_fields_blank(app, client, login):
    login()
    for name in ("Óculos", "Protetor facial"):
        response = register(client, name=name, size="", sku="", ca_number="")
        assert response.status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(Product)) == 3
        assert db.session.scalar(db.select(db.func.count()).select_from(StockVariant)) == 3


def test_registration_with_screenshot_fields(app, client, login):
    login()
    response = register(client, category="TESTE", name="TESTE 3", size="GG",
                        sku="1234", minimum_quantity="0", opening_quantity="100",
                        ca_number="12345", manufacturer="FAB TESTE", model="TEST MODEL",
                        color="TEST COR", lot_number="123456", expiration_date="",
                        replacement_interval_days="", description="TESTE DESCRIÇÃO")
    assert response.status_code == 302
    assert response.headers["X-EPI-Build"] == "2026.10.19.1"
    with app.app_context():
        variant = db.session.scalar(db.select(StockVariant).where(StockVariant.sku == "1234"))
        assert variant.product.name == "TESTE 3"
        assert variant.current_quantity == 100
        assert variant.product.ca_number == "12345"
        assert variant.product.expiration_date is None


def test_existing_product_accepts_new_size_without_losing_metadata(app, client, login):
    login()
    response = register(client, size="G", opening_quantity="7", minimum_quantity="2")
    assert response.status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(Product)) == 1
        product = db.session.get(Product, 1)
        assert product.ca_number == "12345"
        variant = db.session.scalar(db.select(StockVariant).where(StockVariant.size == "G"))
        assert variant.current_quantity == 7
        assert variant.minimum_quantity == 2
        assert db.session.get(StockVariant, 1).current_quantity == 5
        assert db.session.scalar(db.select(StockMovement).where(StockMovement.variant_id == variant.id)).quantity_delta == 7


def test_duplicate_size_preserves_stock(app, client, login):
    login()
    response = register(client, size=" m ", opening_quantity="20")
    assert response.status_code == 200
    assert "tamanho/numeração já está cadastrado" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(StockVariant, 1).current_quantity == 5
        assert db.session.scalar(db.select(db.func.count()).select_from(StockVariant)) == 1


def test_blank_size_duplicate_and_case_insensitive_product(app, client, login):
    login()
    assert register(client, size="").status_code == 302
    response = register(client, category=" proteção da cabeça ", name=" capacete ", size=" ")
    assert response.status_code == 200
    assert "tamanho/numeração já está cadastrado" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(Product)) == 1
        assert db.session.scalar(db.select(db.func.count()).select_from(Category)) == 1


def test_duplicate_sku_rolls_back_new_product(app, client, login):
    login()
    assert register(client, name="Óculos", sku="OC-1").status_code == 302
    response = register(client, name="Luva", sku="OC-1")
    assert response.status_code == 200
    assert "Código / SKU já está em uso" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(db.select(Product).where(Product.name == "Luva")) is None


def test_conflicting_metadata_does_not_modify_existing_product(app, client, login):
    login()
    response = register(client, size="G", ca_number="99999")
    assert response.status_code == 200
    assert "Número do CA" in response.get_data(as_text=True)
    assert "diferente do cadastro existente" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Product, 1).ca_number == "12345"
        assert db.session.scalar(db.select(db.func.count()).select_from(StockVariant)) == 1


def test_edit_cannot_duplicate_size(app, client, login):
    login()
    with app.app_context():
        variant = StockVariant(product_id=1, size="G", current_quantity=0)
        db.session.add(variant)
        db.session.commit()
        variant_id = variant.id
    response = client.post(f"/estoque/{variant_id}/editar", data={
        "category": "Proteção da cabeça", "name": "Capacete", "size": "M", "active": "on"
    })
    assert response.status_code == 200
    assert "tamanho/numeração já está cadastrado" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(StockVariant, variant_id).size == "G"


def test_non_duplicate_integrity_failure_is_not_reported_as_duplicate(app, client, login, monkeypatch):
    login()

    def fail_audit(*args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("NOT NULL constraint failed: audit_logs.action"))

    monkeypatch.setattr("app.inventory.routes.record_audit", fail_audit)
    response = register(client, name="Óculos", opening_quantity="9")
    assert response.status_code == 200
    assert "inconsistência no banco de dados" in response.get_data(as_text=True)
    assert "Já existe" not in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(db.select(Product).where(Product.name == "Óculos")) is None
        assert db.session.scalar(db.select(db.func.count()).select_from(StockMovement)) == 0
