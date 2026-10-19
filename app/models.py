from __future__ import annotations

from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager
from .localtime import local_today


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role in ('admin','operator','viewer')", name="valid_user_role"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    full_name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="operator")
    is_active_account = db.Column(db.Boolean, nullable=False, default=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    failed_login_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True), nullable=True)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    @property
    def is_active(self) -> bool:
        return bool(self.is_active_account)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def can_operate(self) -> bool:
        return self.role in {"admin", "operator"}

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Employee(TimestampMixin, db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    external_code = db.Column(db.String(80), nullable=True, unique=True)
    name = db.Column(db.String(180), nullable=False, index=True)
    job_title = db.Column(db.String(140), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    admission_date = db.Column(db.Date, nullable=True)
    termination_date = db.Column(db.Date, nullable=True)
    shirt_size = db.Column(db.String(30), nullable=True)
    pants_size = db.Column(db.String(30), nullable=True)
    shoe_size = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    solicitations = db.relationship("Solicitation", back_populates="employee")
    deliveries = db.relationship("Delivery", back_populates="employee")


class Category(TimestampMixin, db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    active = db.Column(db.Boolean, nullable=False, default=True)

    products = db.relationship("Product", back_populates="category")


class Product(TimestampMixin, db.Model):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("category_id", "name", name="category_product_name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    name = db.Column(db.String(180), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    ca_number = db.Column(db.String(80), nullable=True)
    manufacturer = db.Column(db.String(180), nullable=True)
    model = db.Column(db.String(120), nullable=True)
    color = db.Column(db.String(80), nullable=True)
    lot_number = db.Column(db.String(100), nullable=True)
    expiration_date = db.Column(db.Date, nullable=True)
    replacement_interval_days = db.Column(db.Integer, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    category = db.relationship("Category", back_populates="products")
    variants = db.relationship(
        "StockVariant", back_populates="product", cascade="all, delete-orphan"
    )


class StockVariant(TimestampMixin, db.Model):
    __tablename__ = "stock_variants"
    __table_args__ = (
        CheckConstraint(
            "minimum_quantity is null or minimum_quantity >= 0", name="min_nonnegative"
        ),
        Index("ix_stock_variant_product_size", "product_id", "size"),
    )

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    size = db.Column(db.String(60), nullable=True)
    sku = db.Column(db.String(100), nullable=True, unique=True)
    minimum_quantity = db.Column(db.Integer, nullable=True)
    current_quantity = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    notes = db.Column(db.Text, nullable=True)

    product = db.relationship("Product", back_populates="variants")
    movements = db.relationship("StockMovement", back_populates="variant")

    @property
    def display_name(self) -> str:
        size = f" · {self.size}" if self.size else ""
        return f"{self.product.name}{size}"

    @property
    def stock_level(self) -> str:
        if self.current_quantity <= 0:
            return "zero"
        if self.minimum_quantity is None:
            return "unset"
        if self.current_quantity <= self.minimum_quantity:
            return "low"
        return "normal"


class Solicitation(TimestampMixin, db.Model):
    __tablename__ = "solicitations"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending','separated','partial','delivered','cancelled')",
            name="valid_solicitation_status",
        ),
        CheckConstraint(
            "priority in ('normal','urgent')", name="valid_solicitation_priority"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), nullable=False, unique=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    requested_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    status = db.Column(db.String(30), nullable=False, default="pending", index=True)
    priority = db.Column(db.String(20), nullable=False, default="normal")
    notes = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    employee = db.relationship("Employee", back_populates="solicitations")
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    items = db.relationship(
        "SolicitationItem", back_populates="solicitation", cascade="all, delete-orphan"
    )
    deliveries = db.relationship("Delivery", back_populates="solicitation")


class SolicitationItem(db.Model):
    __tablename__ = "solicitation_items"
    __table_args__ = (
        CheckConstraint("quantity_requested > 0", name="requested_positive"),
        CheckConstraint("quantity_delivered >= 0", name="delivered_nonnegative"),
        UniqueConstraint("solicitation_id", "variant_id", name="solicitation_variant"),
    )

    id = db.Column(db.Integer, primary_key=True)
    solicitation_id = db.Column(
        db.Integer, db.ForeignKey("solicitations.id"), nullable=False
    )
    variant_id = db.Column(db.Integer, db.ForeignKey("stock_variants.id"), nullable=False)
    quantity_requested = db.Column(db.Integer, nullable=False)
    quantity_delivered = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.String(255), nullable=True)

    solicitation = db.relationship("Solicitation", back_populates="items")
    variant = db.relationship("StockVariant")

    @property
    def remaining_quantity(self) -> int:
        return max(self.quantity_requested - self.quantity_delivered, 0)


class Delivery(TimestampMixin, db.Model):
    __tablename__ = "deliveries"
    __table_args__ = (
        CheckConstraint("status in ('completed','reversed')", name="valid_delivery_status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    receipt_number = db.Column(db.String(60), nullable=False, unique=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    solicitation_id = db.Column(db.Integer, db.ForeignKey("solicitations.id"), nullable=True)
    delivered_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    delivered_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="completed")
    notes = db.Column(db.Text, nullable=True)
    signature_path = db.Column(db.String(500), nullable=False)
    signature_sha256 = db.Column(db.String(64), nullable=False)
    receipt_pdf_path = db.Column(db.String(500), nullable=True)
    receipt_sha256 = db.Column(db.String(64), nullable=True)
    acknowledgement_text = db.Column(db.Text, nullable=False)
    retention_until = db.Column(db.Date, nullable=False)
    reversed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reversed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reversal_reason = db.Column(db.Text, nullable=True)

    employee = db.relationship("Employee", back_populates="deliveries")
    solicitation = db.relationship("Solicitation", back_populates="deliveries")
    delivered_by = db.relationship("User", foreign_keys=[delivered_by_id])
    reversed_by = db.relationship("User", foreign_keys=[reversed_by_id])
    items = db.relationship(
        "DeliveryItem", back_populates="delivery", cascade="all, delete-orphan"
    )
    movements = db.relationship("StockMovement", back_populates="delivery")

    @property
    def has_digital_signature(self) -> bool:
        return bool(self.signature_path and self.signature_sha256)


class DeliveryItem(db.Model):
    __tablename__ = "delivery_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="delivery_quantity_positive"),
        UniqueConstraint("delivery_id", "variant_id", name="delivery_variant"),
    )

    id = db.Column(db.Integer, primary_key=True)
    delivery_id = db.Column(db.Integer, db.ForeignKey("deliveries.id"), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey("stock_variants.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.String(255), nullable=True)

    delivery = db.relationship("Delivery", back_populates="items")
    variant = db.relationship("StockVariant")


class StockMovement(db.Model):
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("quantity_delta <> 0", name="movement_nonzero"),
        CheckConstraint(
            "movement_type in ('entry','delivery','return','adjustment','reversal')",
            name="valid_movement_type",
        ),
        Index("ix_stock_movements_variant_created", "variant_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("stock_variants.id"), nullable=False)
    movement_type = db.Column(db.String(30), nullable=False, index=True)
    quantity_delta = db.Column(db.Integer, nullable=False)
    previous_quantity = db.Column(db.Integer, nullable=False)
    new_quantity = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=True)
    delivery_id = db.Column(db.Integer, db.ForeignKey("deliveries.id"), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    variant = db.relationship("StockVariant", back_populates="movements")
    employee = db.relationship("Employee")
    delivery = db.relationship("Delivery", back_populates="movements")
    created_by = db.relationship("User")


class ReplenishmentOrder(TimestampMixin, db.Model):
    __tablename__ = "replenishment_orders"
    __table_args__ = (
        CheckConstraint(
            "status in ('draft','issued','received','cancelled')",
            name="valid_replenishment_status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(50), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default="draft")
    order_date = db.Column(db.Date, nullable=False, default=local_today)
    notes = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    issued_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_by = db.relationship("User")
    items = db.relationship(
        "ReplenishmentItem", back_populates="order", cascade="all, delete-orphan"
    )


class ReplenishmentItem(db.Model):
    __tablename__ = "replenishment_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="replenishment_quantity_positive"),
        UniqueConstraint("order_id", "variant_id", name="replenishment_variant"),
    )

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("replenishment_orders.id"), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey("stock_variants.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    current_quantity_snapshot = db.Column(db.Integer, nullable=False)
    minimum_quantity_snapshot = db.Column(db.Integer, nullable=True)

    order = db.relationship("ReplenishmentOrder", back_populates="items")
    variant = db.relationship("StockVariant")


class EmailOutbox(db.Model):
    __tablename__ = "email_outbox"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending','processing','sent','failed')", name="valid_email_status"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    to_address = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body_text = db.Column(db.Text, nullable=False)
    body_html = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text, nullable=True)
    dedup_key = db.Column(db.String(180), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    next_attempt_at = db.Column(db.DateTime(timezone=True), nullable=True)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)


class StockAlert(db.Model):
    __tablename__ = "stock_alerts"
    __table_args__ = (
        CheckConstraint("level in ('low','zero')", name="valid_alert_level"),
    )

    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("stock_variants.id"), nullable=False)
    movement_id = db.Column(db.Integer, db.ForeignKey("stock_movements.id"), nullable=False)
    previous_level = db.Column(db.String(20), nullable=False)
    level = db.Column(db.String(20), nullable=False)
    email_outbox_id = db.Column(db.Integer, db.ForeignKey("email_outbox.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    variant = db.relationship("StockVariant")
    movement = db.relationship("StockMovement")
    email_outbox = db.relationship("EmailOutbox")


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    updated_by = db.relationship("User")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(80), nullable=False, index=True)
    entity_type = db.Column(db.String(80), nullable=False)
    entity_id = db.Column(db.String(80), nullable=True)
    before_json = db.Column(db.JSON, nullable=True)
    after_json = db.Column(db.JSON, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    user = db.relationship("User")


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))
