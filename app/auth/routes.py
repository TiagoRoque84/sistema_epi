from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import User


bp = Blueprint("auth", __name__, url_prefix="/auth")


def _safe_next_url(target: str | None) -> bool:
    if not target:
        return False
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return redirect_url.scheme in {"http", "https"} and host_url.netloc == redirect_url.netloc


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip().casefold()
        password = request.form.get("password", "")
        user = db.session.scalar(db.select(User).where(User.username == username))
        now = datetime.now(timezone.utc)

        if user and user.locked_until:
            locked_until = user.locked_until
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            if locked_until > now:
                flash("Acesso temporariamente bloqueado. Tente novamente mais tarde.", "danger")
                return render_template("auth/login.html"), 429

        if not user or not user.is_active or not user.check_password(password):
            if user:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= 5:
                    user.locked_until = now + timedelta(minutes=15)
                    user.failed_login_attempts = 0
                db.session.commit()
            flash("Usuário ou senha inválidos.", "danger")
            return render_template("auth/login.html"), 401

        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        db.session.commit()
        login_user(user, remember=False)
        next_url = request.args.get("next")
        flash(f"Bem-vindo, {user.full_name}.", "success")
        return redirect(next_url if _safe_next_url(next_url) else url_for("main.dashboard"))

    return render_template("auth/login.html")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("Sessão encerrada com segurança.", "info")
    return redirect(url_for("auth.login"))
