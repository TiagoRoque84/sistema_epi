from __future__ import annotations

from flask import current_app

from app.email_service import enqueue_stock_alert
from app.extensions import db
from app.models import StockMovement, StockVariant


def level_for(quantity: int, minimum: int | None) -> str:
    if quantity <= 0:
        return "zero"
    if minimum is None:
        return "unset"
    if quantity <= minimum:
        return "low"
    return "normal"


def apply_movement(
    *,
    variant_id: int,
    movement_type: str,
    quantity_delta: int,
    user_id: int,
    reason: str | None = None,
    employee_id: int | None = None,
    delivery_id: int | None = None,
) -> StockMovement:
    if quantity_delta == 0:
        raise ValueError("A quantidade da movimentação não pode ser zero.")
    variant = db.session.scalar(
        db.select(StockVariant).where(StockVariant.id == variant_id).with_for_update()
    )
    if variant is None:
        raise ValueError("Item de estoque não encontrado.")

    previous_quantity = variant.current_quantity
    new_quantity = previous_quantity + quantity_delta
    if not current_app.config["ALLOW_NEGATIVE_STOCK"] and new_quantity < 0:
        raise ValueError("Saldo insuficiente para concluir a movimentação.")

    previous_level = level_for(previous_quantity, variant.minimum_quantity)
    new_level = level_for(new_quantity, variant.minimum_quantity)
    variant.current_quantity = new_quantity
    movement = StockMovement(
        variant=variant,
        movement_type=movement_type,
        quantity_delta=quantity_delta,
        previous_quantity=previous_quantity,
        new_quantity=new_quantity,
        reason=reason,
        employee_id=employee_id,
        delivery_id=delivery_id,
        created_by_id=user_id,
    )
    db.session.add(movement)
    db.session.flush()
    enqueue_stock_alert(variant, movement, previous_level, new_level)
    return movement
