"""Ponto de entrada da aplicação.

A ORDEM DESTE ARQUIVO É SIGNIFICATIVA.

`app/config.py` lê as variáveis de ambiente no corpo da classe `Config`, isto é,
no instante em que o módulo é importado. Por isso o `.env` precisa ser carregado
ANTES de qualquer import de `app`. Se a ordem se inverte, a configuração congela
nos padrões de desenvolvimento — SQLite em `instance/` — e a validação de
produção nem chega a rodar, porque ela depende de `PRODUCTION_MODE` vir do
mesmo arquivo. O sistema sobe aparentando normalidade e falha no primeiro login.

A CLI do Flask (`flask --app wsgi:app ...`) carrega o `.env` por conta própria
antes de importar a aplicação, então os comandos de linha nunca sofreram com
isso. O `serve.py` e o `email_worker.py`, sim.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def load_environment() -> None:
    """Carrega o .env e confirma que ele realmente chegou ao processo."""
    try:
        env_present = ENV_FILE.name in os.listdir(BASE_DIR)
    except OSError:
        env_present = False

    if not env_present:
        # Desenvolvimento local sem .env: os padrões de app/config.py bastam.
        return

    load_dotenv(ENV_FILE, override=False)

    # python-dotenv não levanta erro quando não consegue abrir o arquivo: apenas
    # registra um aviso e devolve um conjunto vazio. A checagem abaixo é o que
    # transforma esse silêncio em falha explícita.
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError(
            f"O arquivo {ENV_FILE} existe, mas nenhuma configuração foi lida "
            "dele. A causa mais comum é falta de permissão: o arquivo guarda "
            "senhas e fica restrito a SYSTEM e administradores. Execute o "
            "sistema com uma conta que tenha leitura nele, ou libere o acesso "
            "com:\n\n"
            f'    icacls "{ENV_FILE}" /grant "DOMINIO\\conta:(R)"\n\n'
            "Detalhes em README.md."
        )


load_environment()

# Importado depois de propósito: veja a explicação no topo do arquivo.
from app import create_app  # noqa: E402


app = create_app()


# Rede de segurança contra a reintrodução do problema de ordem. Se um import
# futuro voltar a carregar app/config.py cedo demais, a configuração efetiva
# deixará de bater com o .env e o sistema para aqui, em vez de usar um banco
# vazio em silêncio.
_esperado = os.getenv("DATABASE_URL")
if _esperado:
    _scheme_env = _esperado.split("://", 1)[0]
    _scheme_uso = str(app.config["SQLALCHEMY_DATABASE_URI"]).split("://", 1)[0]
    if _scheme_env != _scheme_uso:
        raise RuntimeError(
            "A configuração carregada não corresponde ao .env.\n"
            f"  .env pede : {_scheme_env}\n"
            f"  em uso    : {_scheme_uso}\n"
            "Algum módulo de 'app' foi importado antes de load_environment(). "
            "Carregue o .env antes de qualquer import de 'app'."
        )
