# Sistema de Gestão de EPIs

Aplicação em Python e Flask para cadastro de colaboradores e equipamentos, controle de estoque, solicitações, entregas com assinatura digital ou no papel, comprovantes PDF e alertas por e-mail.

## Conteúdo deste repositório

- Código da aplicação, templates e recursos visuais.
- Estrutura do banco com migrações Alembic, sem registros operacionais.
- Testes automatizados com dados fictícios e assinatura gerada durante o teste.
- Dependências e configuração de exemplo sem credenciais reais.

Cadastros reais, planilhas, bancos de dados, assinaturas, comprovantes, relatórios, logs, backups e scripts de ajustes pontuais de estoque não fazem parte desta publicação. Os scripts e caminhos específicos do servidor interno também foram excluídos. Os recursos visuais mantêm a identidade do Grupo Transer.

## Executar localmente no Windows

Requer Python 3.11 ou superior. Em uma pasta local, execute no PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Copie a chave gerada para `SECRET_KEY` no seu `.env`. Em seguida:

```powershell
.\.venv\Scripts\python.exe -m flask --app wsgi:app db upgrade
.\.venv\Scripts\python.exe -m flask --app wsgi:app create-admin
.\.venv\Scripts\python.exe serve.py
```

Acesse http://127.0.0.1:8080. O comando `create-admin` solicita os dados da sua conta e uma senha; não há conta operacional pré-cadastrada. Informe seu próprio e-mail. O banco começa vazio.

O exemplo usa SQLite e suprime o envio de e-mails. Os dados locais ficam em `instance/`, ignorada pelo Git.

## Produção

Use PostgreSQL e configure no `.env` local:

- `PRODUCTION_MODE=1`.
- Uma `SECRET_KEY` aleatória com ao menos 40 caracteres.
- `DATABASE_URL=postgresql+psycopg://usuario:senha@localhost:5432/epi` com suas credenciais; codifique caracteres especiais da senha na URL.
- `DATA_DIR` apontando para uma pasta protegida para assinaturas e comprovantes.
- `APP_BASE_URL`, `APP_HOST` e os parâmetros SMTP do seu ambiente.
- `DEFAULT_ALERT_EMAIL` com o destinatário real e `MAIL_SUPPRESS_SEND=0` para habilitar os alertas.

Execute as migrações e crie o administrador como no roteiro local. Execute `serve.py` para o servidor web e `email_worker.py` em um processo separado para a fila de e-mails. Configure HTTPS, `SESSION_COOKIE_SECURE=1`, permissões de acesso e backups conforme seu ambiente. Senhas e dados operacionais ficam fora do GitHub.

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Os testes usam um banco SQLite em memória e arquivos temporários. Os nomes, contas, senhas e desenhos de assinatura dos testes são exclusivamente fictícios.

## Publicação de alterações

O `.gitignore` limita as pastas da raiz e bloqueia formatos de dados e documentos. Revise também o conteúdo de cada alteração com `git diff --cached` antes de enviar: um arquivo de código pode conter dados pessoais ou segredos mesmo quando a extensão é permitida.
