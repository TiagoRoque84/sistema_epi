from __future__ import annotations

import os
from pathlib import Path

import click
from flask import Flask, render_template
from flask.cli import with_appcontext

from .config import Config
from .extensions import csrf, db, login_manager, migrate


def create_app(config_object: type[Config] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object or Config)
    validate_production_config(app)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["SIGNATURE_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["RECEIPT_DIR"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.admin.routes import bp as admin_bp
    from app.auth.routes import bp as auth_bp
    from app.deliveries.routes import bp as deliveries_bp
    from app.employees.routes import bp as employees_bp
    from app.inventory.routes import bp as inventory_bp
    from app.main.routes import bp as main_bp
    from app.solicitations.routes import bp as solicitations_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(solicitations_bp)
    app.register_blueprint(deliveries_bp)
    app.register_blueprint(admin_bp)

    register_cli(app)
    register_security_headers(app)
    register_template_helpers(app)
    register_error_handlers(app)
    return app


def validate_production_config(app: Flask) -> None:
    if not app.config["PRODUCTION_MODE"]:
        return
    problems: list[str] = []
    secret = str(app.config["SECRET_KEY"])
    database_url = str(app.config["SQLALCHEMY_DATABASE_URI"])
    smtp_password = str(app.config["SMTP_PASSWORD"])
    if secret == "dev-only-change-before-production" or secret.startswith("troque-") or len(secret) < 40:
        problems.append("SECRET_KEY segura")
    if not database_url.startswith("postgresql+") or "troque-" in database_url:
        problems.append("DATABASE_URL do PostgreSQL")
    if not app.config["SMTP_USERNAME"] or not smtp_password or smtp_password.startswith("senha-de-"):
        problems.append("credenciais SMTP do Gmail")
    if problems:
        raise RuntimeError("Configuração de produção incompleta: " + ", ".join(problems) + ".")


def register_security_headers(app: Flask) -> None:
    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-EPI-Build", "2026.10.19.1")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'",
        )
        return response


def register_template_helpers(app: Flask) -> None:
    from app.localtime import format_date, format_datetime

    # Os horários vêm do banco em UTC; ambos os filtros convertem para o fuso
    # configurado em TIMEZONE antes de formatar.
    app.add_template_filter(format_date, "date_br")
    app.add_template_filter(format_datetime, "datetime_br")


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/error.html", code=403, title="Acesso não permitido", message="Seu perfil não possui permissão para esta ação."), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/error.html", code=404, title="Página não encontrada", message="O endereço informado não existe ou o registro foi removido."), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template("errors/error.html", code=500, title="Não foi possível concluir", message="Ocorreu um erro interno. Nenhuma alteração incompleta foi mantida."), 500


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    @with_appcontext
    def init_db_command():
        """Create database tables for the first local run."""
        from app import models  # noqa: F401
        from app.settings_service import DEFAULT_ACKNOWLEDGEMENT, set_setting

        db.create_all()
        if db.session.get(models.AppSetting, "alert_email") is None:
            set_setting("alert_email", app.config["DEFAULT_ALERT_EMAIL"])
        if db.session.get(models.AppSetting, "acknowledgement_text") is None:
            set_setting("acknowledgement_text", DEFAULT_ACKNOWLEDGEMENT)
        db.session.commit()
        click.echo("Banco inicializado.")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--full-name", prompt="Nome completo")
    @click.option("--email", prompt="E-mail", default="alertas@example.invalid")
    @click.password_option(confirmation_prompt=True)
    @with_appcontext
    def create_admin_command(username: str, full_name: str, email: str, password: str):
        """Create the first administrator account."""
        from app.models import User

        normalized_username = username.strip().casefold()
        if db.session.scalar(db.select(User).where(User.username == normalized_username)):
            raise click.ClickException("Esse usuário já existe.")
        if len(password) < 10:
            raise click.ClickException("A senha deve possuir ao menos 10 caracteres.")
        user = User(
            username=normalized_username,
            full_name=full_name.strip(),
            email=email.strip().casefold() or None,
            role="admin",
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Administrador '{normalized_username}' criado.")

    @app.cli.command("process-email-queue")
    @click.option("--limit", default=25, type=click.IntRange(1, 100))
    @with_appcontext
    def process_email_queue_command(limit: int):
        """Send queued stock alerts and persist retries."""
        from app.email_service import process_pending_emails

        sent, failed = process_pending_emails(limit)
        click.echo(f"Enviados: {sent}; falhas: {failed}.")

    @app.cli.command("importar-planilha")
    @click.option("--arquivo", required=True, type=click.Path(exists=True, dir_okay=False))
    @click.option("--aplicar", is_flag=True, default=False, help="Grava no banco. Sem esta opção, apenas relata.")
    @click.option("--relatorio", type=click.Path(dir_okay=False), default=None, help="Salva o relatório em arquivo.")
    @click.option("--usuario", default=None, help="Login do responsável pelo lançamento. Padrão: o primeiro administrador.")
    @with_appcontext
    def importar_planilha_command(arquivo: str, aplicar: bool, relatorio: str | None, usuario: str | None):
        """Importa colaboradores, catálogo e saldo inicial da planilha de EPIs."""
        from pathlib import Path

        from app.importer import apply_plan, build_plan, report_lines
        from app.models import User

        plan = build_plan(arquivo)
        lines = report_lines(plan)
        click.echo("\n".join(lines))

        if relatorio:
            Path(relatorio).write_text("\n".join(lines) + "\n", encoding="utf-8")
            click.echo(f"\nRelatório salvo em {relatorio}")

        if not aplicar:
            click.echo("\nNada foi gravado. Revise o relatório e repita com --aplicar.")
            return

        if plan.blocking:
            raise click.ClickException(
                f"{len(plan.blocking)} erro(s) impedem a importação. Corrija a planilha e execute novamente."
            )

        if usuario:
            responsible = db.session.scalar(db.select(User).where(User.username == usuario.strip().casefold()))
        else:
            responsible = db.session.scalar(db.select(User).where(User.role == "admin").order_by(User.id))
        if responsible is None:
            raise click.ClickException("Nenhum administrador encontrado para registrar as movimentações.")

        counts = apply_plan(plan, responsible, Path(arquivo).name)
        db.session.commit()

        click.echo("")
        click.echo("Importação concluída. Registros criados:")
        for label, total in counts.items():
            click.echo(f"  {label}: {total}")
        click.echo(f"\nMovimentações lançadas em nome de '{responsible.username}'.")
