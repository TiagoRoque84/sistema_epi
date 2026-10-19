from __future__ import annotations

import smtplib
from datetime import timedelta
from email.message import EmailMessage

from flask import current_app
from markupsafe import escape
from sqlalchemy import or_

from app.extensions import db
from app.models import EmailOutbox, StockAlert, StockMovement, StockVariant, utcnow
from app.settings_service import alert_email


def enqueue_stock_alert(
    variant: StockVariant,
    movement: StockMovement,
    previous_level: str,
    new_level: str,
) -> StockAlert | None:
    if new_level not in {"low", "zero"} or previous_level == new_level:
        return None

    level_label = "ZERADO" if new_level == "zero" else "BAIXO"
    subject = f"[EPIs Transer] Estoque {level_label}: {variant.display_name}"
    url = f"{current_app.config['APP_BASE_URL'].rstrip('/')}/estoque/{variant.id}"
    minimum = "Não definido" if variant.minimum_quantity is None else str(variant.minimum_quantity)
    text = (
        f"Alerta de estoque {level_label.lower()}\n\n"
        f"Item: {variant.product.name}\n"
        f"Tamanho: {variant.size or 'Único'}\n"
        f"Saldo atual: {variant.current_quantity}\n"
        f"Estoque mínimo: {minimum}\n"
        f"Última movimentação: {movement.quantity_delta:+d}\n"
        f"Acesse: {url}\n"
    )
    html = f"""
    <div style="font-family:Arial,sans-serif;color:#172033;max-width:620px">
      <div style="background:#172a4d;color:#fff;padding:18px 22px;border-radius:10px 10px 0 0">
        <strong>GRUPO TRANSER · CONTROLE DE EPIs</strong>
      </div>
      <div style="border:1px solid #dfe5ec;border-top:0;padding:22px;border-radius:0 0 10px 10px">
        <h2 style="margin-top:0;color:{'#c73737' if new_level == 'zero' else '#b76a11'}">Estoque {level_label.lower()}</h2>
        <p><strong>Item:</strong> {escape(variant.product.name)}<br>
        <strong>Tamanho:</strong> {escape(variant.size or 'Único')}<br>
        <strong>Saldo atual:</strong> {variant.current_quantity}<br>
        <strong>Estoque mínimo:</strong> {minimum}<br>
        <strong>Última movimentação:</strong> {movement.quantity_delta:+d}</p>
        <p><a href="{escape(url)}" style="display:inline-block;background:#2d8b4e;color:#fff;text-decoration:none;padding:11px 16px;border-radius:8px">Abrir sistema</a></p>
      </div>
    </div>
    """
    outbox = EmailOutbox(
        to_address=alert_email(),
        subject=subject,
        body_text=text,
        body_html=html,
        dedup_key=f"stock:{movement.id}:{new_level}",
    )
    db.session.add(outbox)
    db.session.flush()
    alert = StockAlert(
        variant_id=variant.id,
        movement_id=movement.id,
        previous_level=previous_level,
        level=new_level,
        email_outbox_id=outbox.id,
    )
    db.session.add(alert)
    return alert


def process_pending_emails(limit: int = 25) -> tuple[int, int]:
    now = utcnow()
    messages = db.session.scalars(
        db.select(EmailOutbox)
        .where(
            EmailOutbox.status.in_(["pending", "failed"]),
            or_(EmailOutbox.next_attempt_at.is_(None), EmailOutbox.next_attempt_at <= now),
            EmailOutbox.attempts < 5,
        )
        .order_by(EmailOutbox.created_at)
        .limit(limit)
    ).all()
    sent = 0
    failed = 0
    for queued in messages:
        queued.status = "processing"
        db.session.commit()
        try:
            _send_message(queued)
            queued.status = "sent"
            queued.sent_at = utcnow()
            queued.last_error = None
            sent += 1
        except Exception as exc:  # SMTP failures are persisted for safe retry.
            queued.attempts += 1
            queued.status = "failed"
            queued.last_error = str(exc)[:2000]
            queued.next_attempt_at = utcnow() + timedelta(minutes=min(5 * queued.attempts, 60))
            failed += 1
        db.session.commit()
    return sent, failed


def _send_message(queued: EmailOutbox) -> None:
    if current_app.config["MAIL_SUPPRESS_SEND"]:
        return
    username = current_app.config["SMTP_USERNAME"]
    password = current_app.config["SMTP_PASSWORD"]
    sender = current_app.config["MAIL_DEFAULT_SENDER"] or username
    if not username or not password or not sender:
        raise RuntimeError("Credenciais SMTP não configuradas.")

    message = EmailMessage()
    message["Subject"] = queued.subject
    message["From"] = sender
    message["To"] = queued.to_address
    message.set_content(queued.body_text)
    message.add_alternative(queued.body_html, subtype="html")

    with smtplib.SMTP(
        current_app.config["SMTP_HOST"], current_app.config["SMTP_PORT"], timeout=30
    ) as smtp:
        smtp.ehlo()
        if current_app.config["SMTP_USE_TLS"]:
            smtp.starttls()
            smtp.ehlo()
        smtp.login(username, password)
        smtp.send_message(message)
