from __future__ import annotations

import base64
import io

import pytest
from PIL import Image, ImageDraw

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import Category, Employee, Product, StockVariant, User


@pytest.fixture()
def app(tmp_path):
    class Config(TestConfig):
        DATA_DIR = tmp_path / "data"
        SIGNATURE_DIR = DATA_DIR / "signatures"
        RECEIPT_DIR = DATA_DIR / "receipts"
        SECRET_KEY = "test-secret"

    application = create_app(Config)
    with application.app_context():
        db.create_all()
        admin = User(username="admin", full_name="Administrador", role="admin")
        admin.set_password("senha-segura-123")
        viewer = User(username="consulta", full_name="Consulta", role="viewer")
        viewer.set_password("senha-segura-456")
        employee = Employee(name="Colaborador Fictício", job_title="Operadora")
        category = Category(name="Proteção da cabeça")
        product = Product(name="Capacete", category=category, ca_number="12345")
        variant = StockVariant(product=product, size="M", minimum_quantity=4, current_quantity=5)
        db.session.add_all([admin, viewer, employee, category, product, variant])
        db.session.commit()
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def login(client):
    def do_login(username="admin", password="senha-segura-123"):
        return client.post("/auth/login", data={"username": username, "password": password})
    return do_login


@pytest.fixture()
def signature_data_url():
    image = Image.new("RGBA", (600, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.line([(60, 115), (140, 60), (220, 118), (340, 54), (490, 112)], fill="#172a4d", width=6)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
