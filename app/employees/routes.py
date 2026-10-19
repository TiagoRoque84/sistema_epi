from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.audit import model_snapshot, record_audit
from app.decorators import operator_required
from app.extensions import db
from app.helpers import clean, get_or_404, optional_date, require_text
from app.models import Employee


bp = Blueprint("employees", __name__, url_prefix="/colaboradores")


@bp.get("")
@login_required
def index():
    query = request.args.get("q", "").strip()
    statement = db.select(Employee)
    if query:
        like = f"%{query}%"
        statement = statement.where(or_(Employee.name.ilike(like), Employee.job_title.ilike(like)))
    employees = db.session.scalars(statement.order_by(Employee.active.desc(), Employee.name)).all()
    return render_template("employees/index.html", employees=employees, query=query)


@bp.route("/novo", methods=["GET", "POST"])
@operator_required
def create():
    employee = Employee(active=True)
    if request.method == "POST":
        try:
            _assign(employee)
            db.session.add(employee)
            db.session.flush()
            record_audit("create", "Employee", employee.id, None, model_snapshot(employee))
            db.session.commit()
            flash("Colaborador cadastrado.", "success")
            return redirect(url_for("employees.detail", employee_id=employee.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return render_template("employees/form.html", employee=employee, editing=False)


@bp.get("/<int:employee_id>")
@login_required
def detail(employee_id: int):
    employee = get_or_404(Employee, employee_id)
    deliveries = sorted(employee.deliveries, key=lambda item: item.delivered_at, reverse=True)[:30]
    requests = sorted(employee.solicitations, key=lambda item: item.requested_at, reverse=True)[:20]
    return render_template("employees/detail.html", employee=employee, deliveries=deliveries, requests=requests)


@bp.route("/<int:employee_id>/editar", methods=["GET", "POST"])
@operator_required
def edit(employee_id: int):
    employee = get_or_404(Employee, employee_id)
    if request.method == "POST":
        before = model_snapshot(employee)
        try:
            _assign(employee)
            record_audit("update", "Employee", employee.id, before, model_snapshot(employee))
            db.session.commit()
            flash("Cadastro atualizado.", "success")
            return redirect(url_for("employees.detail", employee_id=employee.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return render_template("employees/form.html", employee=employee, editing=True)


def _assign(employee: Employee) -> None:
    employee.name = require_text(request.form.get("name"), field="Nome", max_length=180)
    employee.external_code = clean(request.form.get("external_code"))
    employee.job_title = clean(request.form.get("job_title"))
    employee.admission_date = optional_date(request.form.get("admission_date"), field="Admissão")
    employee.termination_date = optional_date(request.form.get("termination_date"), field="Desligamento")
    employee.shirt_size = clean(request.form.get("shirt_size"))
    employee.pants_size = clean(request.form.get("pants_size"))
    employee.shoe_size = clean(request.form.get("shoe_size"))
    employee.email = clean(request.form.get("email"))
    employee.notes = clean(request.form.get("notes"))
    employee.active = request.form.get("active") == "on"
