"""Acesso ao banco de dados (SQLite).

O banco é um arquivo só, em instance/alexandria.db. Na primeira vez que o sistema
roda, ele é criado com as tabelas do schema.sql e os dados de exemplo do dados_exemplo.sql.
"""
import os
import sqlite3

from flask import current_app, g
from werkzeug.security import generate_password_hash

PASTA = os.path.dirname(os.path.abspath(__file__))

# Contas da equipe criadas na primeira vez que o sistema roda (as mesmas da versão desktop).
EQUIPE_PADRAO = [
    ("augusto.bento@alexandria.com.br", "Adm1958", "Augusto Bento", "Administrador Geral"),
    ("karine.varela@alexandria.com.br", "Adm2608", "Karine Varela", "Bibliotecária Chefe"),
]


def conectar(caminho: str) -> sqlite3.Connection:
    """Abre a conexão com o SQLite, deixa ler as colunas pelo nome e liga as chaves estrangeiras."""
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row          # deixa usar linha["titulo"] em vez de linha[1]
    con.execute("PRAGMA foreign_keys = ON")
    return con


def get_db() -> sqlite3.Connection:
    """Uma conexão por acesso, guardada no "g" do Flask para não abrir várias vezes."""
    if "db" not in g:
        g.db = conectar(current_app.config["BANCO"])
    return g.db


def fechar_db(_erro=None) -> None:
    """Fecha a conexão quando o acesso termina."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def criar_banco(caminho: str, com_exemplos: bool = True) -> None:
    """Cria as tabelas (se ainda não existirem) e, se o banco estiver vazio,
    carrega os dados de exemplo e as contas da equipe.
    """
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
    """Liga o banco ao Flask: fecha a conexão sozinho no fim de cada acesso e cria o banco se precisar."""
    app.teardown_appcontext(fechar_db)
    criar_banco(app.config["BANCO"], app.config.get("CARREGAR_EXEMPLOS", True))
