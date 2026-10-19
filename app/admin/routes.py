from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.audit import model_snapshot, record_audit
from app.decorators import admin_required
from app.extensions import db
from app.helpers import clean, get_or_404, require_text
from app.models import AppSetting, AuditLog, EmailOutbox, User
from app.settings_service import DEFAULT_ACKNOWLEDGEMENT, acknowledgement_text, alert_email, set_setting


bp = Blueprint("admin", __name__, url_prefix="/administracao")


@bp.get("")
@admin_required
def index():
    users = db.session.scalars(db.select(User).order_by(User.full_name)).all()
    queued_count = db.session.scalar(db.select(db.func.count()).select_from(EmailOutbox).where(EmailOutbox.status.in_(["pending", "failed"])))
    return render_template("admin/index.html", users=users, queued_count=queued_count, alert_address=alert_email(), smtp_ready=bool(current_app.config["SMTP_USERNAME"] and current_app.config["SMTP_PASSWORD"]))


@bp.route("/usuarios/novo", methods=["GET", "POST"])
@admin_required
def user_create():
    user = User(role="operator", is_active_account=True)
    if request.method == "POST":
        try:
            _assign_user(user, creating=True)
            db.session.add(user)
            db.session.flush()
            record_audit("create", "User", user.id, None, model_snapshot(user))
            db.session.commit()
            flash("Usuário criado.", "success")
            return redirect(url_for("admin.index"))
        except (ValueError, IntegrityError) as exc:
            db.session.rollback()
            flash("Esse nome de usuário já existe." if isinstance(exc, IntegrityError) else str(exc), "danger")
    return render_template("admin/user_form.html", user=user, editing=False)


@bp.route("/usuarios/<int:user_id>/editar", methods=["GET", "POST"])
@admin_required
def user_edit(user_id: int):
    user = get_or_404(User, user_id)
    if request.method == "POST":
        before = model_snapshot(user)
        try:
            _assign_user(user, creating=False)
            if user.id == current_user.id and not user.is_active_account:
                raise ValueError("Você não pode desativar o próprio usuário.")
            record_audit("update", "User", user.id, before, model_snapshot(user))
            db.session.commit()
            flash("Usuário atualizado.", "success")
            return redirect(url_for("admin.index"))
        except (ValueError, IntegrityError) as exc:
            db.session.rollback()
            flash("Esse nome de usuário já existe." if isinstance(exc, IntegrityError) else str(exc), "danger")
    return render_template("admin/user_form.html", user=user, editing=True)


@bp.route("/configuracoes", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        try:
            address = require_text(request.form.get("alert_email"), field="E-mail de alerta", max_length=255)
            if "@" not in address:
                raise ValueError("Informe um e-mail de alerta válido.")
            text = require_text(request.form.get("acknowledgement_text"), field="Termo de recebimento", max_length=5000)
            before = {"alert_email": alert_email(), "acknowledgement_text": acknowledgement_text()}
            set_setting("alert_email", address.casefold(), current_user.id)
            set_setting("acknowledgement_text", text, current_user.id)
            record_audit("update", "AppSettings", "global", before, {"alert_email": address.casefold(), "acknowledgement_text": text})
            db.session.commit()
            flash("Configurações salvas.", "success")
            return redirect(url_for("admin.settings"))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return render_template("admin/settings.html", alert_address=alert_email(), acknowledgement=acknowledgement_text(), default_acknowledgement=DEFAULT_ACKNOWLEDGEMENT)


@bp.get("/auditoria")
@admin_required
def audit():
    logs = db.session.scalars(db.select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500)).all()
    return render_template("admin/audit.html", logs=logs)


def _assign_user(user: User, *, creating: bool) -> None:
    user.username = require_text(request.form.get("username"), field="Usuário", max_length=80).casefold()
    user.full_name = require_text(request.form.get("full_name"), field="Nome completo", max_length=160)
    user.email = clean(request.form.get("email"))
    role = request.form.get("role", "operator")
    if role not in {"admin", "operator", "viewer"}:
        raise ValueError("Perfil de acesso inválido.")
    user.role = role
    user.is_active_account = request.form.get("is_active") == "on"
    password = request.form.get("password", "")
    if creating or password:
        if len(password) < 10:
            raise ValueError("A senha deve possuir ao menos 10 caracteres.")
        user.set_password(password)
