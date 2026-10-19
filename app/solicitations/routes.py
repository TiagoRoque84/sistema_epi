from __future__ import annotations

import uuid

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.audit import model_snapshot, record_audit
from app.decorators import operator_required
from app.extensions import db
from app.helpers import clean, get_or_404, integer
from app.models import Employee, Solicitation, SolicitationItem, StockVariant


bp = Blueprint("solicitations", __name__, url_prefix="/solicitacoes")


@bp.get("")
@login_required
def index():
    status = request.args.get("status", "").strip()
    statement = db.select(Solicitation)
    if status:
        statement = statement.where(Solicitation.status == status)
    items = db.session.scalars(statement.order_by(Solicitation.requested_at.desc()).limit(300)).all()
    return render_template("solicitations/index.html", solicitations=items, status=status)


@bp.route("/nova", methods=["GET", "POST"])
@operator_required
def create():
    employees = db.session.scalars(db.select(Employee).where(Employee.active.is_(True)).order_by(Employee.name)).all()
    variants = _active_variants()
    if request.method == "POST":
        try:
            employee_id = integer(request.form.get("employee_id"), field="Colaborador", minimum=1)
            employee = db.session.get(Employee, employee_id)
            if not employee or not employee.active:
                raise ValueError("Selecione um colaborador ativo.")
            priority = request.form.get("priority", "normal")
            if priority not in {"normal", "urgent"}:
                raise ValueError("Prioridade inválida.")
            parsed_items = _parse_items()
            solicitation = Solicitation(number=f"SOL-{uuid.uuid4().hex[:8].upper()}", employee=employee, priority=priority, notes=clean(request.form.get("notes")), created_by_id=current_user.id)
            for variant_id, quantity in parsed_items.items():
                solicitation.items.append(SolicitationItem(variant_id=variant_id, quantity_requested=quantity))
            db.session.add(solicitation)
            db.session.flush()
            record_audit("create", "Solicitation", solicitation.id, None, model_snapshot(solicitation))
            db.session.commit()
            flash(f"Solicitação {solicitation.number} registrada.", "success")
            return redirect(url_for("solicitations.detail", solicitation_id=solicitation.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return render_template("solicitations/form.html", employees=employees, variants=variants)


@bp.get("/<int:solicitation_id>")
@login_required
def detail(solicitation_id: int):
    solicitation = get_or_404(Solicitation, solicitation_id)
    return render_template("solicitations/detail.html", solicitation=solicitation)


@bp.post("/<int:solicitation_id>/separar")
@operator_required
def separate(solicitation_id: int):
    solicitation = get_or_404(Solicitation, solicitation_id)
    if solicitation.status not in {"pending", "partial"}:
        flash("Essa solicitação não pode ser marcada como separada.", "warning")
    else:
        before = model_snapshot(solicitation)
        solicitation.status = "separated"
        record_audit("separate", "Solicitation", solicitation.id, before, model_snapshot(solicitation))
        db.session.commit()
        flash("Solicitação marcada como separada.", "success")
    return redirect(url_for("solicitations.detail", solicitation_id=solicitation.id))


@bp.post("/<int:solicitation_id>/cancelar")
@operator_required
def cancel(solicitation_id: int):
    solicitation = get_or_404(Solicitation, solicitation_id)
    if solicitation.status == "delivered":
        flash("Uma solicitação entregue não pode ser cancelada. Estorne a entrega, se necessário.", "danger")
    elif solicitation.status == "cancelled":
        flash("A solicitação já está cancelada.", "info")
    else:
        before = model_snapshot(solicitation)
        solicitation.status = "cancelled"
        record_audit("cancel", "Solicitation", solicitation.id, before, model_snapshot(solicitation))
        db.session.commit()
        flash("Solicitação cancelada.", "success")
    return redirect(url_for("solicitations.detail", solicitation_id=solicitation.id))


def _active_variants():
    return db.session.scalars(db.select(StockVariant).where(StockVariant.active.is_(True)).order_by(StockVariant.product_id, StockVariant.size)).all()


def _parse_items() -> dict[int, int]:
    ids = request.form.getlist("variant_id")
    quantities = request.form.getlist("quantity")
    if not ids or len(ids) != len(quantities):
        raise ValueError("Inclua ao menos um EPI.")
    parsed: dict[int, int] = {}
    for raw_id, raw_quantity in zip(ids, quantities):
        variant_id = integer(raw_id, field="EPI", minimum=1)
        quantity = integer(raw_quantity, field="Quantidade", minimum=1)
        variant = db.session.get(StockVariant, variant_id)
        if not variant or not variant.active:
            raise ValueError("Um dos EPIs selecionados não está mais disponível.")
        parsed[variant_id] = parsed.get(variant_id, 0) + quantity
    return parsed
