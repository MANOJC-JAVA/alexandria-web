-- ============================================================================
-- ALEXANDRIA WEB - Sistema de Gestão de Biblioteca
-- Modelo físico do banco de dados (SQLite 3)
-- ============================================================================
PRAGMA foreign_keys = ON;

-- Equipe da biblioteca: contas que operam o sistema (bibliotecário / administrador)
CREATE TABLE IF NOT EXISTS funcionarios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT    NOT NULL UNIQUE,
    senha_hash  TEXT    NOT NULL,              -- senha guardada com hash (PBKDF2), nunca em texto puro
    nome        TEXT    NOT NULL,
    cargo       TEXT    NOT NULL,
    ativo       INTEGER NOT NULL DEFAULT 1
);

-- Usuários da biblioteca (leitores e equipe cadastrada no acervo de pessoas)
CREATE TABLE IF NOT EXISTS pessoas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT    NOT NULL,
    email       TEXT    NOT NULL UNIQUE,
    telefone    TEXT,
    tipo        TEXT    NOT NULL CHECK (tipo IN ('Estudante','Professor','Funcionário','Bibliotecário','Administrador')),
    matricula   TEXT    NOT NULL UNIQUE,       -- também é a senha de acesso do leitor (UC17)
    ativo       INTEGER NOT NULL DEFAULT 1,
    desde       TEXT    NOT NULL               -- data de cadastro (AAAA-MM-DD)
);

-- Acervo
CREATE TABLE IF NOT EXISTS livros (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo       TEXT    NOT NULL,
    autor        TEXT    NOT NULL,
    genero       TEXT    NOT NULL,
    ano          INTEGER,
    isbn         TEXT,
    local        TEXT,
    sinopse      TEXT,
    palavras     TEXT,                         -- palavras-chave usadas pela IA
    total        INTEGER NOT NULL DEFAULT 1 CHECK (total >= 1),
    disponiveis  INTEGER NOT NULL DEFAULT 1 CHECK (disponiveis >= 0),
    tom          TEXT    NOT NULL DEFAULT 'GOLD',   -- cor da capa
    especial     INTEGER NOT NULL DEFAULT 0,        -- obra do Cofre Especial
    popularidade INTEGER NOT NULL DEFAULT 0
);

-- Empréstimos (devolvido = NULL enquanto o empréstimo está ativo)
CREATE TABLE IF NOT EXISTS emprestimos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    livro_id    INTEGER NOT NULL REFERENCES livros(id),
    pessoa_id   INTEGER NOT NULL REFERENCES pessoas(id),
    retirada    TEXT    NOT NULL,
    previsto    TEXT    NOT NULL,
    devolvido   TEXT,
    renovacoes  INTEGER NOT NULL DEFAULT 0 CHECK (renovacoes BETWEEN 0 AND 2)
);

-- Reservas de títulos
CREATE TABLE IF NOT EXISTS reservas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    livro_id    INTEGER NOT NULL REFERENCES livros(id),
    pessoa_id   INTEGER NOT NULL REFERENCES pessoas(id),
    data        TEXT    NOT NULL,
    estado      TEXT    NOT NULL DEFAULT 'AGUARDANDO'
                CHECK (estado IN ('AGUARDANDO','PRONTA','ATENDIDA','CANCELADA'))
);

CREATE INDEX IF NOT EXISTS idx_emp_pessoa  ON emprestimos(pessoa_id);
CREATE INDEX IF NOT EXISTS idx_emp_livro   ON emprestimos(livro_id);
CREATE INDEX IF NOT EXISTS idx_res_livro   ON reservas(livro_id, estado);
