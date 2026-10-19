"""Processador da fila de alertas por e-mail.

A ordem dos imports importa: `wsgi` carrega o `.env` antes de qualquer módulo
de `app` ser importado. Inverter isso faz a configuração congelar nos padrões
de desenvolvimento. Veja a explicação completa no topo de `wsgi.py`.
"""

from __future__ import annotations

import logging
import os
import signal
import threading

# Primeiro o wsgi, que carrega o .env. Só depois qualquer coisa de 'app'.
from wsgi import app

from app.email_service import process_pending_emails  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
stop_event = threading.Event()


def stop(*_args) -> None:
    stop_event.set()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    interval = max(int(os.getenv("EMAIL_WORKER_INTERVAL_SECONDS", "60")), 30)
    logging.info("Processador de alertas iniciado; intervalo de %s segundos.", interval)
    while not stop_event.is_set():
        with app.app_context():
            sent, failed = process_pending_emails()
            if sent or failed:
                logging.info("Fila processada: %s enviados, %s falhas.", sent, failed)
        stop_event.wait(interval)
