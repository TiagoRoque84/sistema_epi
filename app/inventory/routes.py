from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.audit import model_snapshot, record_audit
from app.decorators import operator_required
from app.extensions import db
from app.helpers import clean, get_or_404, integer, optional_date, optional_integer, require_text
from app.inventory.services import apply_movement
from app.localtime import local_today
from app.models import Category, Product, ReplenishmentItem, ReplenishmentOrder, StockMovement, StockVariant


bp = Blueprint("inventory", __name__, url_prefix="/estoque")


@bp.get("")
@login_required
def index():
    query = request.args.get("q", "").strip()
    level = request.args.get("nivel", "").strip()
    statement = db.select(StockVariant).join(StockVariant.product).join(Product.category)
    if query:
        like = f"%{query}%"
        statement = statement.where(or_(Product.name.ilike(like), StockVariant.size.ilike(like), Category.name.ilike(like), Product.ca_number.ilike(like)))
    if level == "zero":
        statement = statement.where(StockVariant.current_quantity <= 0)
    elif level == "low":
        statement = statement.where(StockVariant.current_quantity > 0, StockVariant.minimum_quantity.is_not(None), StockVariant.current_quantity <= StockVariant.minimum_quantity)
    variants = db.session.scalars(statement.order_by(Category.name, Product.name, StockVariant.size)).all()
    return render_template("inventory/index.html", variants=variants, query=query, level=level)


@bp.route("/produtos/novo", methods=["GET", "POST"])
@operator_required
def product_create():
    product = Product(active=True)
    categories = db.session.scalars(db.select(Category).order_by(Category.name)).all()
    if request.method == "POST":
        try:
            category_name = require_text(request.form.get("category"), field="Categoria", max_length=100)
            category = db.session.scalar(db.select(Category).where(db.func.lower(db.func.trim(Category.name)) == category_name.lower()))
            if category is None:
                category = Category(name=category_name)
                db.session.add(category)
                db.session.flush()
            _assign_product(product, category.id)
            existing = db.session.scalar(
                db.select(Product).where(
                    Product.category_id == category.id,
                    db.func.lower(db.func.trim(Product.name)) == product.name.lower(),
                ).with_for_update()
            )
            new_product = existing is None
            if existing is not None:
                _check_product_metadata(product, existing)
                product = existing
            else:
                db.session.add(product)
                db.session.flush()
            size = clean(request.form.get("size"))
            sku = clean(request.form.get("sku"))
            _check_variant_unique(product.id, size, sku)
            variant = StockVariant(product=product, size=size, sku=sku, active=request.form.get("active") == "on", minimum_quantity=optional_integer(request.form.get("minimum_quantity"), field="Estoque mínimo", minimum=0), current_quantity=0)
            db.session.add(variant)
            db.session.flush()
            opening = optional_integer(request.form.get("opening_quantity"), field="Saldo inicial") or 0
            if opening:
                apply_movement(variant_id=variant.id, movement_type="entry", quantity_delta=opening, user_id=current_user.id, reason="Saldo inicial")
            if new_product:
                record_audit("create", "Product", product.id, None, model_snapshot(product))
            record_audit("create", "StockVariant", variant.id, None, model_snapshot(variant))
            db.session.commit()
            flash("EPI cadastrado no estoque.", "success")
            return redirect(url_for("inventory.detail", variant_id=variant.id))
        except (ValueError, IntegrityError) as exc:
            db.session.rollback()
            flash(_friendly_error(exc), "danger")
    return render_template("inventory/product_form.html", product=product, categories=categories)


@bp.get("/<int:variant_id>")
@login_required
def detail(variant_id: int):
    variant = get_or_404(StockVariant, variant_id)
    movements = db.session.scalars(db.select(StockMovement).where(StockMovement.variant_id == variant.id).order_by(StockMovement.created_at.desc()).limit(100)).all()
    return render_template("inventory/detail.html", variant=variant, movements=movements)


@bp.route("/<int:variant_id>/editar", methods=["GET", "POST"])
@operator_required
def variant_edit(variant_id: int):
    variant = get_or_404(StockVariant, variant_id)
    product = variant.product
    categories = db.session.scalars(db.select(Category).order_by(Category.name)).all()
    if request.method == "POST":
        before = {"product": model_snapshot(product), "variant": model_snapshot(variant)}
        try:
            category_name = require_text(request.form.get("category"), field="Categoria", max_length=100)
            category = db.session.scalar(db.select(Category).where(db.func.lower(db.func.trim(Category.name)) == category_name.lower()))
            if category is None:
                category = Category(name=category_name)
                db.session.add(category)
                db.session.flush()
            # Serialize size changes with creation of variants of this product.
            db.session.execute(db.select(Product.id).where(Product.id == product.id).with_for_update())
            _check_variant_unique(product.id, clean(request.form.get("size")), clean(request.form.get("sku")), exclude_id=variant.id)
            _assign_product(product, category.id)
            variant.size = clean(request.form.get("size"))
            variant.sku = clean(request.form.get("sku"))
            variant.minimum_quantity = optional_integer(request.form.get("minimum_quantity"), field="Estoque mínimo", minimum=0)
            variant.notes = clean(request.form.get("variant_notes"))
            variant.active = request.form.get("active") == "on"
            record_audit("update", "StockVariant", variant.id, before, {"product": model_snapshot(product), "variant": model_snapshot(variant)})
            db.session.commit()
            flash("EPI atualizado.", "success")
            return redirect(url_for("inventory.detail", variant_id=variant.id))
        except (ValueError, IntegrityError) as exc:
            db.session.rollback()
            flash(_friendly_error(exc), "danger")
    return render_template("inventory/product_form.html", product=product, variant=variant, categories=categories, editing=True)


@bp.route("/<int:variant_id>/movimentar", methods=["GET", "POST"])
@operator_required
def move(variant_id: int):
    variant = get_or_404(StockVariant, variant_id)
    if request.method == "POST":
        try:
            movement_type = request.form.get("movement_type", "")
            quantity = integer(request.form.get("quantity"), field="Quantidade", minimum=1)
            if movement_type not in {"entry", "return", "adjustment_add", "adjustment_remove"}:
                raise ValueError("Selecione um tipo de movimentação válido.")
            stored_type = "adjustment" if movement_type.startswith("adjustment") else movement_type
            delta = -quantity if movement_type == "adjustment_remove" else quantity
            reason = require_text(request.form.get("reason"), field="Motivo", max_length=255)
            movement = apply_movement(variant_id=variant.id, movement_type=stored_type, quantity_delta=delta, user_id=current_user.id, reason=reason)
            record_audit("stock_movement", "StockMovement", movement.id, None, model_snapshot(movement))
            db.session.commit()
            flash(f"Movimentação registrada. Novo saldo: {variant.current_quantity}.", "success")
            return redirect(url_for("inventory.detail", variant_id=variant.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return render_template("inventory/move.html", variant=variant)


@bp.get("/reposicao")
@login_required
def replenishment():
    variants = db.session.scalars(db.select(StockVariant).join(StockVariant.product).where(StockVariant.active.is_(True), StockVariant.minimum_quantity.is_not(None), StockVariant.current_quantity <= StockVariant.minimum_quantity).order_by(StockVariant.current_quantity, Product.name)).all()
    orders = db.session.scalars(db.select(ReplenishmentOrder).order_by(ReplenishmentOrder.created_at.desc()).limit(20)).all()
    return render_template("inventory/replenishment.html", variants=variants, orders=orders)


@bp.post("/reposicao/gerar")
@operator_required
def replenishment_create():
    variant_ids = request.form.getlist("variant_id")
    quantities = request.form.getlist("quantity")
    if not variant_ids or len(variant_ids) != len(quantities):
        flash("Selecione ao menos um item para reposição.", "danger")
        return redirect(url_for("inventory.replenishment"))
    try:
        number = f"REP-{local_today():%Y%m%d}-{db.session.scalar(db.select(db.func.count()).select_from(ReplenishmentOrder)) + 1:04d}"
        order = ReplenishmentOrder(number=number, created_by_id=current_user.id, notes=clean(request.form.get("notes")))
        db.session.add(order)
        seen: set[int] = set()
        for raw_id, raw_quantity in zip(variant_ids, quantities):
            variant_id = integer(raw_id, field="Item", minimum=1)
            quantity = integer(raw_quantity, field="Quantidade", minimum=1)
            if variant_id in seen:
                continue
            seen.add(variant_id)
            variant = get_or_404(StockVariant, variant_id)
            order.items.append(ReplenishmentItem(variant=variant, quantity=quantity, current_quantity_snapshot=variant.current_quantity, minimum_quantity_snapshot=variant.minimum_quantity))
        db.session.flush()
        record_audit("create", "ReplenishmentOrder", order.id, None, model_snapshot(order))
        db.session.commit()
        flash(f"Pedido {order.number} criado como rascunho.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("inventory.replenishment"))


def _assign_product(product: Product, category_id: int) -> None:
    product.category_id = category_id
    product.name = require_text(request.form.get("name"), field="Nome do EPI", max_length=180)
    product.description = clean(request.form.get("description"))
    product.ca_number = clean(request.form.get("ca_number"))
    product.manufacturer = clean(request.form.get("manufacturer"))
    product.model = clean(request.form.get("model"))
    product.color = clean(request.form.get("color"))
    product.lot_number = clean(request.form.get("lot_number"))
    product.expiration_date = optional_date(request.form.get("expiration_date"), field="Validade")
    product.replacement_interval_days = optional_integer(request.form.get("replacement_interval_days"), field="Prazo de troca", minimum=1)
    product.active = request.form.get("active") == "on"


def _check_variant_unique(product_id: int, size: str | None, sku: str | None, *, exclude_id: int | None = None) -> None:
    same_size = db.select(StockVariant.id).where(
        StockVariant.product_id == product_id,
        db.func.coalesce(db.func.lower(db.func.trim(StockVariant.size)), "") == (size or "").lower(),
    )
    same_sku = db.select(StockVariant.id).where(StockVariant.sku == sku)
    if exclude_id is not None:
        same_size = same_size.where(StockVariant.id != exclude_id)
        same_sku = same_sku.where(StockVariant.id != exclude_id)
    if db.session.scalar(same_size) is not None:
        raise ValueError("Este EPI com esse tamanho/numeração já está cadastrado (inclusive se estiver inativo). Para adicionar saldo, use Movimentar no item existente.")
    if sku and db.session.scalar(same_sku) is not None:
        raise ValueError("Código / SKU já está em uso em outro item. Informe outro código ou deixe o campo vazio.")


def _check_product_metadata(submitted: Product, existing: Product) -> None:
    # A new size shares the product data. Never silently replace its CA or lot.
    fields = {
        "ca_number": "Número do CA", "manufacturer": "Fabricante", "model": "Modelo",
        "color": "Cor", "lot_number": "Lote", "expiration_date": "Validade",
        "replacement_interval_days": "Prazo de troca", "description": "Descrição",
    }
    for field, label in fields.items():
        value = getattr(submitted, field)
        if value is not None and value != getattr(existing, field):
            raise ValueError(f"{label} diferente do cadastro existente desse EPI. Para outro modelo, CA ou lote, use um nome distinto; para corrigir os dados atuais, use Editar no item existente.")


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, IntegrityError):
        diagnostic = getattr(exc.orig, "diag", None)
        constraint = getattr(diagnostic, "constraint_name", None)
        if constraint == "category_product_name" or "UNIQUE constraint failed: products.category_id, products.name" in str(exc.orig):
            return "Já existe um EPI com esse nome nesta categoria. Use outro nome ou cadastre um novo tamanho pelo formulário de cadastro."
        if constraint == "uq_stock_variants_sku" or "UNIQUE constraint failed: stock_variants.sku" in str(exc.orig):
            return "Código / SKU já está em uso em outro item. Informe outro código ou deixe o campo vazio."
        # Log only diagnostic identifiers, never SQL parameters or submitted data.
        current_app.logger.error("Falha de integridade no cadastro de EPI: tipo=%s sqlstate=%s constraint=%s", type(exc.orig).__name__, getattr(exc.orig, "sqlstate", None), constraint)
        return "Não foi possível salvar o EPI por uma inconsistência no banco de dados. Nenhuma alteração foi salva. Informe o administrador para verificar o registro técnico."
    return str(exc)
