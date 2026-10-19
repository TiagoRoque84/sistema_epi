from __future__ import annotations

from flask import current_app

from app.extensions import db
from app.models import AppSetting


NR6_CLAUSE_HEADING = "Referência normativa - NR-6"
NR6_CLAUSE = (
    f"{NR6_CLAUSE_HEADING} (itens 6.5.1, alíneas c e d; 6.6.1; e 6.7.2). "
    "O fornecimento dos EPIs deve ocorrer sem custo ao empregado, com proteção "
    "compatível com os riscos e registro de cada entrega. Comprometo-me a usar "
    "os equipamentos recebidos para a proteção a que se destinam, conforme as "
    "instruções da empresa, cuidar da limpeza, guarda e conservação e informar "
    "perdas, danos ou condições que prejudiquem seu uso. A empresa deve prestar "
    "as informações de utilização e realizar os treinamentos cabíveis. Permanecem "
    "sob responsabilidade da empresa a higienização e a manutenção periódica, "
    "quando aplicáveis, e a reposição imediata nos casos de dano ou perda "
    "(item 6.5.1, alíneas f e g)."
)


DEFAULT_ACKNOWLEDGEMENT = (
    "Declaro para os devidos fins que recebi da empresa o(s) equipamento(s) de "
    "proteção individual (EPI) descrito(s) neste comprovante, em perfeitas condições "
    "de uso. Comprometo-me a utilizá-lo(s) durante a jornada de trabalho, zelar por "
    "sua guarda e conservação e devolvê-lo(s) quando solicitado. Declaro que recebi "
    "as orientações necessárias para uso adequado."
)


def get_setting(key: str, default: str = "") -> str:
    setting = db.session.get(AppSetting, key)
    return setting.value if setting else default


def set_setting(key: str, value: str, user_id: int | None = None) -> AppSetting:
    setting = db.session.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value=value, updated_by_id=user_id)
        db.session.add(setting)
    else:
        setting.value = value
        setting.updated_by_id = user_id
    return setting


def alert_email() -> str:
    return get_setting("alert_email", current_app.config["DEFAULT_ALERT_EMAIL"])


def acknowledgement_text() -> str:
    text = get_setting("acknowledgement_text", DEFAULT_ACKNOWLEDGEMENT)
    # Inclui a referência também quando já existe um termo personalizado.
    # Ao salvar o texto completo na administração, não duplica a cláusula.
    if NR6_CLAUSE_HEADING not in text:
        return f"{text.rstrip()}\n\n{NR6_CLAUSE}"
    return text
