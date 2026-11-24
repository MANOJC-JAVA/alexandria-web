"""
Camada de acesso ao banco de dados (SQLite).

O arquivo do banco fica em  instance/alexandria.db  e é criado automaticamente
na primeira execução, com o modelo de schema.sql e os dados de exemplo de
dados_exemplo.sql.
"""
import os
import sqlite3

from flask import current_app, g
from werkzeug.security import generate_password_hash

PASTA = os.path.dirname(os.path.abspath(__file__))

# Contas da equipe criadas na primeira execução (as mesmas da versão desktop).
EQUIPE_PADRAO = [
    ("augusto.bento@alexandria.com.br", "Adm1958", "Augusto Bento", "Administrador Geral"),
    ("karine.varela@alexandria.com.br", "Adm2608", "Karine Varela", "Bibliotecária Chefe"),
]


def conectar(caminho: str) -> sqlite3.Connection:
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row          # linhas acessíveis por nome de coluna
    con.execute("PRAGMA foreign_keys = ON")
    return con


def get_db() -> sqlite3.Connection:
    """Uma conexão por requisição, guardada no objeto g do Flask."""
    if "db" not in g:
        g.db = conectar(current_app.config["BANCO"])
    return g.db


def fechar_db(_erro=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def criar_banco(caminho: str, com_exemplos: bool = True) -> None:
    """Cria as tabelas e, se o banco estiver vazio, carrega os dados de exemplo."""
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    con = conectar(caminho)
    with open(os.path.join(PASTA, "schema.sql"), encoding="utf-8") as f:
        con.executescript(f.read())
    vazio = con.execute("SELECT COUNT(*) FROM livros").fetchone()[0] == 0
    if vazio and com_exemplos:
        with open(os.path.join(PASTA, "dados_exemplo.sql"), encoding="utf-8") as f:
            con.executescript(f.read())
    if con.execute("SELECT COUNT(*) FROM funcionarios").fetchone()[0] == 0:
        for email, senha, nome, cargo in EQUIPE_PADRAO:
            con.execute(
                "INSERT INTO funcionarios (email, senha_hash, nome, cargo) VALUES (?, ?, ?, ?)",
                (email, generate_password_hash(senha), nome, cargo),
            )
    con.commit()
    con.close()


def iniciar_app(app) -> None:
    app.teardown_appcontext(fechar_db)
    criar_banco(app.config["BANCO"], app.config.get("CARREGAR_EXEMPLOS", True))
