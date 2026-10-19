from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.audit import model_snapshot, record_audit
from app.decorators import operator_required
from app.deliveries.documents import decode_signature, generate_receipt, save_signature
from app.extensions import db
from app.helpers import clean, get_or_404, integer, require_text
from app.inventory.services import apply_movement
from app.localtime import to_local
from app.models import Delivery, DeliveryItem, Employee, Solicitation, SolicitationItem, StockVariant
from app.settings_service import acknowledgement_text


bp = Blueprint("deliveries", __name__, url_prefix="/entregas")


@bp.get("")
@login_required
def index():
    deliveries = db.session.scalars(db.select(Delivery).order_by(Delivery.delivered_at.desc()).limit(300)).all()
    return render_template("deliveries/index.html", deliveries=deliveries)


@bp.route("/nova", methods=["GET", "POST"])
@operator_required
def create():
    employees = db.session.scalars(db.select(Employee).where(Employee.active.is_(True)).order_by(Employee.name)).all()
    variants = db.session.scalars(db.select(StockVariant).where(StockVariant.active.is_(True)).order_by(StockVariant.product_id, StockVariant.size)).all()
    solicitation = None
    raw_solicitation_id = request.args.get("solicitacao") or request.form.get("solicitation_id")
    if raw_solicitation_id:
        try:
            solicitation = db.session.get(Solicitation, int(raw_solicitation_id))
        except ValueError:
            solicitation = None
    if request.method == "POST":
        signature_path = None
        receipt_path = None
        try:
            employee_id = integer(request.form.get("employee_id"), field="Colaborador", minimum=1)
            employee = db.session.get(Employee, employee_id)
            if not employee or not employee.active:
                raise ValueError("Selecione um colaborador ativo.")
            if solicitation and solicitation.employee_id != employee.id:
                raise ValueError("A solicitação selecionada pertence a outro colaborador.")
            if solicitation and solicitation.status in {"cancelled", "delivered"}:
                raise ValueError("Essa solicitação não aceita novas entregas.")
            parsed_items = _parse_delivery_items(solicitation)
            signature_mode = request.form.get("signature_mode", "digital")
            if signature_mode not in {"digital", "paper"}:
                raise ValueError("Selecione uma forma de assinatura válida.")
            signature_raw = decode_signature(request.form.get("signature_data", "")) if signature_mode == "digital" else None
            delivered_at = datetime.now(timezone.utc)
            # O instante é gravado em UTC, mas o número do comprovante e o prazo
            # de retenção seguem a data local: é a data que o colaborador vê no
            # documento e a que conta para o prazo legal.
            local_date = to_local(delivered_at).date()
            # Campos vazios representam ausência de assinatura digital e mantêm
            # compatibilidade com as colunas NOT NULL do banco já instalado.
            signature_path, signature_hash = save_signature(signature_raw, delivered_at) if signature_raw else ("", "")
            delivery = Delivery(
                receipt_number=f"EPI-{local_date:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
                employee=employee,
                solicitation=solicitation,
                delivered_at=delivered_at,
                delivered_by_id=current_user.id,
                notes=clean(request.form.get("notes")),
                signature_path=signature_path,
                signature_sha256=signature_hash,
                acknowledgement_text=acknowledgement_text(),
                retention_until=_retention_date(local_date),
            )
            db.session.add(delivery)
            db.session.flush()
            for variant_id, quantity in parsed_items.items():
                delivery.items.append(DeliveryItem(variant_id=variant_id, quantity=quantity))
                apply_movement(variant_id=variant_id, movement_type="delivery", quantity_delta=-quantity, user_id=current_user.id, reason=f"Entrega {delivery.receipt_number}", employee_id=employee.id, delivery_id=delivery.id)
                if solicitation:
                    item = next(item for item in solicitation.items if item.variant_id == variant_id)
                    item.quantity_delivered += quantity
            if solicitation:
                _refresh_solicitation_status(solicitation)
            db.session.flush()
            receipt_path, receipt_hash = generate_receipt(delivery)
            delivery.receipt_pdf_path = receipt_path
            delivery.receipt_sha256 = receipt_hash
            snapshot = model_snapshot(delivery)
            snapshot["signature_mode"] = signature_mode
            record_audit("create", "Delivery", delivery.id, None, snapshot)
            db.session.commit()
            if delivery.has_digital_signature:
                flash(f"Entrega {delivery.receipt_number} registrada e assinada.", "success")
            else:
                flash(f"Entrega {delivery.receipt_number} registrada sem assinatura digital. Imprima o comprovante para colher a assinatura no papel.", "success")
            return redirect(url_for("deliveries.detail", delivery_id=delivery.id))
        except (ValueError, StopIteration) as exc:
            db.session.rollback()
            _remove_artifact(signature_path)
            _remove_artifact(receipt_path)
            message = "Um item não pertence à solicitação selecionada." if isinstance(exc, StopIteration) else str(exc)
            flash(message, "danger")
    return render_template("deliveries/form.html", employees=employees, variants=variants, solicitation=solicitation, acknowledgement=acknowledgement_text())


@bp.get("/<int:delivery_id>")
@login_required
def detail(delivery_id: int):
    delivery = get_or_404(Delivery, delivery_id)
    return render_template("deliveries/detail.html", delivery=delivery)


@bp.get("/<int:delivery_id>/comprovante")
@login_required
def receipt(delivery_id: int):
    delivery = get_or_404(Delivery, delivery_id)
    path = _artifact_path(delivery.receipt_pdf_path)
    if not path or not path.is_file():
        flash("O comprovante não foi encontrado no armazenamento.", "danger")
        return redirect(url_for("deliveries.detail", delivery_id=delivery.id))
    return send_file(path, mimetype="application/pdf", as_attachment=False, download_name=f"{delivery.receipt_number}.pdf")


@bp.get("/<int:delivery_id>/assinatura")
@login_required
def signature(delivery_id: int):
    delivery = get_or_404(Delivery, delivery_id)
    if not delivery.has_digital_signature:
        flash("Esta entrega foi registrada para assinatura no papel. Abra o comprovante PDF para imprimir.", "info")
        return redirect(url_for("deliveries.detail", delivery_id=delivery.id))
    path = _artifact_path(delivery.signature_path)
    if not path or not path.is_file():
        flash("A assinatura não foi encontrada no armazenamento.", "danger")
        return redirect(url_for("deliveries.detail", delivery_id=delivery.id))
    return send_file(path, mimetype="image/png", as_attachment=False)


@bp.post("/<int:delivery_id>/estornar")
@operator_required
def reverse(delivery_id: int):
    delivery = get_or_404(Delivery, delivery_id)
    if delivery.status == "reversed":
        flash("Essa entrega já foi estornada.", "info")
        return redirect(url_for("deliveries.detail", delivery_id=delivery.id))
    try:
        reason = require_text(request.form.get("reason"), field="Motivo do estorno", max_length=500)
        before = model_snapshot(delivery)
        for item in delivery.items:
            apply_movement(variant_id=item.variant_id, movement_type="reversal", quantity_delta=item.quantity, user_id=current_user.id, reason=f"Estorno {delivery.receipt_number}: {reason}", employee_id=delivery.employee_id, delivery_id=delivery.id)
            if delivery.solicitation:
                solicitation_item = next((candidate for candidate in delivery.solicitation.items if candidate.variant_id == item.variant_id), None)
                if solicitation_item:
                    solicitation_item.quantity_delivered = max(0, solicitation_item.quantity_delivered - item.quantity)
        if delivery.solicitation:
            _refresh_solicitation_status(delivery.solicitation)
        delivery.status = "reversed"
        delivery.reversed_at = datetime.now(timezone.utc)
        delivery.reversed_by_id = current_user.id
        delivery.reversal_reason = reason
        record_audit("reverse", "Delivery", delivery.id, before, model_snapshot(delivery))
        db.session.commit()
        flash("Entrega estornada. O estoque foi recomposto sem apagar o histórico.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("deliveries.detail", delivery_id=delivery.id))


def _parse_delivery_items(solicitation: Solicitation | None) -> dict[int, int]:
    ids = request.form.getlist("variant_id")
    quantities = request.form.getlist("quantity")
    if not ids or len(ids) != len(quantities):
        raise ValueError("Inclua ao menos um EPI na entrega.")
    allowed = {item.variant_id: item.remaining_quantity for item in solicitation.items} if solicitation else None
    parsed: dict[int, int] = {}
    for raw_id, raw_quantity in zip(ids, quantities):
        variant_id = integer(raw_id, field="EPI", minimum=1)
        quantity = integer(raw_quantity, field="Quantidade", minimum=1)
        variant = db.session.get(StockVariant, variant_id)
        if not variant or not variant.active:
            raise ValueError("Um dos EPIs selecionados não está disponível.")
        parsed[variant_id] = parsed.get(variant_id, 0) + quantity
    if allowed is not None:
        for variant_id, quantity in parsed.items():
            if variant_id not in allowed or quantity > allowed[variant_id]:
                raise ValueError("A quantidade entregue excede o saldo da solicitação.")
    return parsed


def _refresh_solicitation_status(solicitation: Solicitation) -> None:
    remaining = sum(item.remaining_quantity for item in solicitation.items)
    delivered = sum(item.quantity_delivered for item in solicitation.items)
    solicitation.status = "delivered" if remaining == 0 else ("partial" if delivered else "pending")


def _retention_date(start: date) -> date:
    try:
        return start.replace(year=start.year + int(current_app.config["RECEIPT_RETENTION_YEARS"]))
    except ValueError:
        return start.replace(month=2, day=28, year=start.year + int(current_app.config["RECEIPT_RETENTION_YEARS"]))


def _artifact_path(relative: str | None) -> Path | None:
    if not relative:
        return None
    base = Path(current_app.config["DATA_DIR"]).resolve()
    candidate = (base / relative).resolve()
    return candidate if candidate == base or base in candidate.parents else None


def _remove_artifact(relative: str | None) -> None:
    path = _artifact_path(relative)
    if path and path.is_file():
        path.unlink()
