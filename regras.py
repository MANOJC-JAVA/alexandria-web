"""
Regras de negócio do Alexandria (portadas de dados/Biblioteca.java).

Todas as operações recebem a conexão com o banco e devolvem None quando dão
certo ou uma mensagem de erro (str) explicando por que a operação foi recusada.
"""
import sqlite3
from datetime import date, timedelta

LIMITE_RENOVACOES = 2
TIPOS = ["Estudante", "Professor", "Funcionário", "Bibliotecário", "Administrador"]
TONS = ["GOLD", "CRIMSON", "BLUE", "FOREST", "PURPLE", "NOIR"]
POR_PAGINA = 8


def hoje() -> date:
    return date.today()


def limite_emprestimos(tipo: str) -> int:
    return 3 if tipo == "Estudante" else 5


def prazo_padrao(tipo: str) -> int:
    return 14 if tipo == "Estudante" else 21


def eh_leitor(tipo: str) -> bool:
    return tipo in ("Estudante", "Professor")


def _iso(d) -> str:
    return d.isoformat() if isinstance(d, date) else str(d)


# --------------------------------------------------------------------- consultas
def livro(db, livro_id):
    return db.execute("SELECT * FROM livros WHERE id = ?", (livro_id,)).fetchone()


def pessoa(db, pessoa_id):
    return db.execute("SELECT * FROM pessoas WHERE id = ?", (pessoa_id,)).fetchone()


def generos(db) -> list:
    return [r[0] for r in db.execute("SELECT DISTINCT genero FROM livros ORDER BY genero")]


def catalogo(db, busca="", genero="", disponibilidade="", ordem="titulo", pagina=1):
    """UC03: lista paginada com busca, filtros e ordenação."""
    sql, args = "SELECT * FROM livros WHERE 1=1", []
    if busca:
        sql += " AND (titulo LIKE ? OR autor LIKE ? OR isbn LIKE ? OR palavras LIKE ?)"
        args += [f"%{busca}%"] * 4
    if genero:
        sql += " AND genero = ?"
        args.append(genero)
    if disponibilidade == "disponivel":
        sql += " AND disponiveis > 0"
    elif disponibilidade == "indisponivel":
        sql += " AND disponiveis = 0"
    ordens = {"titulo": "titulo COLLATE NOCASE", "autor": "autor COLLATE NOCASE",
              "ano": "ano DESC", "popularidade": "popularidade DESC"}
    total = db.execute(f"SELECT COUNT(*) FROM ({sql})", args).fetchone()[0]
    paginas = max(1, -(-total // POR_PAGINA))
    pagina = min(max(1, pagina), paginas)
    sql += f" ORDER BY {ordens.get(ordem, ordens['titulo'])} LIMIT ? OFFSET ?"
    linhas = db.execute(sql, args + [POR_PAGINA, (pagina - 1) * POR_PAGINA]).fetchall()
    return linhas, total, pagina, paginas


EMP_SQL = """
SELECT e.*, l.titulo, l.autor, p.nome, p.tipo
  FROM emprestimos e JOIN livros l ON l.id = e.livro_id JOIN pessoas p ON p.id = e.pessoa_id
"""


def emprestimos_ativos(db, pessoa_id=None):
    sql, args = EMP_SQL + " WHERE e.devolvido IS NULL", []
    if pessoa_id:
        sql += " AND e.pessoa_id = ?"
        args.append(pessoa_id)
    return db.execute(sql + " ORDER BY e.previsto", args).fetchall()


def historico(db, pessoa_id):
    return db.execute(EMP_SQL + " WHERE e.pessoa_id = ? ORDER BY e.retirada DESC", (pessoa_id,)).fetchall()


def ids_lidos(db, pessoa_id) -> list:
    """Livros que a pessoa já pegou emprestado: base do perfil de leitor da IA."""
    return [r[0] for r in db.execute(
        "SELECT DISTINCT livro_id FROM emprestimos WHERE pessoa_id = ?", (pessoa_id,))]


def reservas(db, pessoa_id=None, so_abertas=False):
    sql = """SELECT r.*, l.titulo, l.disponiveis, p.nome FROM reservas r
               JOIN livros l ON l.id = r.livro_id JOIN pessoas p ON p.id = r.pessoa_id WHERE 1=1"""
    args = []
    if pessoa_id:
        sql += " AND r.pessoa_id = ?"
        args.append(pessoa_id)
    if so_abertas:
        sql += " AND r.estado IN ('AGUARDANDO','PRONTA')"
    return db.execute(sql + " ORDER BY r.data DESC, r.id DESC", args).fetchall()


def separados_para_outros(db, livro_id, pessoa_id) -> int:
    """Exemplares já separados para reservas PRONTAS de outras pessoas."""
    return db.execute("""SELECT COUNT(*) FROM reservas WHERE livro_id = ? AND estado = 'PRONTA'
                          AND pessoa_id <> ?""", (livro_id, pessoa_id)).fetchone()[0]


def atrasado(emp, dia=None) -> bool:
    return emp["devolvido"] is None and emp["previsto"] < _iso(dia or hoje())


def status_emprestimo(emp, dia=None) -> str:
    if emp["devolvido"]:
        return "Devolvido"
    return "Atrasado" if atrasado(emp, dia) else "No prazo"


# --------------------------------------------------------------------- operações
def emprestar(db, livro_id, pessoa_id, retirada=None, previsto=None):
    """UC06: registra um empréstimo. Devolve None se deu certo ou o motivo da recusa."""
    l, p = livro(db, livro_id), pessoa(db, pessoa_id)
    if l is None:
        return "Selecione um livro."
    if p is None:
        return "Selecione um leitor."
    if not p["ativo"]:
        return f"{p['nome']} está inativo e não pode emprestar."
    if l["disponiveis"] <= 0:
        return f"\"{l['titulo']}\" está sem exemplares disponíveis."
    if l["disponiveis"] <= separados_para_outros(db, l["id"], p["id"]):
        return f"O exemplar de \"{l['titulo']}\" está separado para uma reserva de outro leitor."
    retirada = retirada or hoje()
    previsto = previsto or (retirada + timedelta(days=prazo_padrao(p["tipo"])))
    if _iso(previsto) < _iso(retirada):
        return "A devolução não pode ser antes da retirada."
    ativos = emprestimos_ativos(db, p["id"])
    for e in ativos:
        if e["livro_id"] == l["id"]:
            return f"{p['nome']} já está com este livro."
        if atrasado(e):
            return f"{p['nome']} tem devolução em atraso ({e['titulo']})."
    if len(ativos) >= limite_emprestimos(p["tipo"]):
        return f"{p['nome']} atingiu o limite de {limite_emprestimos(p['tipo'])} empréstimos."
    try:
        db.execute("INSERT INTO emprestimos (livro_id, pessoa_id, retirada, previsto) VALUES (?, ?, ?, ?)",
                   (l["id"], p["id"], _iso(retirada), _iso(previsto)))
        db.execute("UPDATE livros SET disponiveis = disponiveis - 1, popularidade = popularidade + 1 WHERE id = ?",
                   (l["id"],))
        # a reserva que a pessoa tinha para este livro foi atendida
        db.execute("""UPDATE reservas SET estado = 'ATENDIDA'
                       WHERE livro_id = ? AND pessoa_id = ? AND estado IN ('AGUARDANDO','PRONTA')""",
                   (l["id"], p["id"]))
        db.commit()
    except sqlite3.Error as erro:
        db.rollback()
        return f"Não foi possível registrar: {erro}"
    return None


def devolver(db, emprestimo_id):
    """UC07: fecha o empréstimo; a primeira reserva aguardando o título passa a PRONTA."""
    e = db.execute("SELECT * FROM emprestimos WHERE id = ?", (emprestimo_id,)).fetchone()
    if e is None:
        return "Empréstimo não encontrado."
    if e["devolvido"]:
        return "Este empréstimo já foi devolvido."
    db.execute("UPDATE emprestimos SET devolvido = ? WHERE id = ?", (_iso(hoje()), e["id"]))
    db.execute("UPDATE livros SET disponiveis = disponiveis + 1 WHERE id = ?", (e["livro_id"],))
    r = db.execute("""SELECT id FROM reservas WHERE livro_id = ? AND estado = 'AGUARDANDO'
                      ORDER BY data, id LIMIT 1""", (e["livro_id"],)).fetchone()
    if r:
        db.execute("UPDATE reservas SET estado = 'PRONTA' WHERE id = ?", (r["id"],))
    db.commit()
    return None


def renovar(db, emprestimo_id):
    """UC08: no máximo 2 renovações; não renova se houver reserva aguardando o livro."""
    e = db.execute(EMP_SQL + " WHERE e.id = ?", (emprestimo_id,)).fetchone()
    if e is None:
        return "Empréstimo não encontrado."
    if e["devolvido"]:
        return "Empréstimo já devolvido."
    if e["renovacoes"] >= LIMITE_RENOVACOES:
        return f"Limite de {LIMITE_RENOVACOES} renovações atingido."
    fila = db.execute("SELECT 1 FROM reservas WHERE livro_id = ? AND estado = 'AGUARDANDO'",
                      (e["livro_id"],)).fetchone()
    if fila:
        return "Há uma reserva aguardando este livro."
    base = hoje() if atrasado(e) else date.fromisoformat(e["previsto"])
    novo = base + timedelta(days=prazo_padrao(e["tipo"]))
    db.execute("UPDATE emprestimos SET previsto = ?, renovacoes = renovacoes + 1 WHERE id = ?",
               (_iso(novo), e["id"]))
    db.commit()
    return None


def reservar(db, livro_id, pessoa_id):
    """UC09: cria a reserva no estado AGUARDANDO."""
    l, p = livro(db, livro_id), pessoa(db, pessoa_id)
    if l is None or p is None:
        return "Selecione livro e leitor."
    if not p["ativo"]:
        return f"{p['nome']} está inativo."
    if l["disponiveis"] > separados_para_outros(db, l["id"], p["id"]):
        return f"\"{l['titulo']}\" tem exemplar disponível: registre o empréstimo, não é preciso reservar."
    com_ele = db.execute("""SELECT 1 FROM emprestimos WHERE livro_id = ? AND pessoa_id = ?
                             AND devolvido IS NULL""", (l["id"], p["id"])).fetchone()
    if com_ele:
        return f"{p['nome']} já está com este livro."
    dup = db.execute("""SELECT 1 FROM reservas WHERE livro_id = ? AND pessoa_id = ?
                         AND estado IN ('AGUARDANDO','PRONTA')""", (l["id"], p["id"])).fetchone()
    if dup:
        return "Esta reserva já existe."
    db.execute("INSERT INTO reservas (livro_id, pessoa_id, data) VALUES (?, ?, ?)",
               (l["id"], p["id"], _iso(hoje())))
    db.commit()
    return None


def cancelar_reserva(db, reserva_id, pessoa_id=None):
    """UC10. Se pessoa_id for informado (leitor), só cancela reservas dele."""
    r = db.execute("SELECT * FROM reservas WHERE id = ?", (reserva_id,)).fetchone()
    if r is None or (pessoa_id and r["pessoa_id"] != pessoa_id):
        return "Reserva não encontrada."
    if r["estado"] not in ("AGUARDANDO", "PRONTA"):
        return "Só reservas ativas podem ser canceladas."
    db.execute("UPDATE reservas SET estado = 'CANCELADA' WHERE id = ?", (r["id"],))
    if r["estado"] == "PRONTA":
        # o exemplar que estava separado passa para o próximo da fila
        prox = db.execute("""SELECT id FROM reservas WHERE livro_id = ? AND estado = 'AGUARDANDO'
                             ORDER BY data, id LIMIT 1""", (r["livro_id"],)).fetchone()
        if prox:
            db.execute("UPDATE reservas SET estado = 'PRONTA' WHERE id = ?", (prox["id"],))
    db.commit()
    return None


def cadastrar_livro(db, dados: dict):
    """UC05: valida e grava uma obra. Devolve (id, None) ou (None, erro)."""
    obrig = {"titulo": "Título", "autor": "Autor", "genero": "Gênero"}
    faltando = [nome for campo, nome in obrig.items() if not (dados.get(campo) or "").strip()]
    if faltando:
        return None, "Preencha os campos obrigatórios: " + ", ".join(faltando) + "."
    try:
        ano = int(dados.get("ano") or 0)
        qtd = int(dados.get("quantidade") or 1)
    except ValueError:
        return None, "Ano e quantidade devem ser números."
    if qtd < 1:
        return None, "A quantidade de exemplares deve ser pelo menos 1."
    tom = dados.get("tom") if dados.get("tom") in TONS else "GOLD"
    palavras = (dados.get("palavras") or "").strip() or f"{dados['genero']} {dados.get('sinopse', '')}".lower()
    cur = db.execute(
        """INSERT INTO livros (titulo, autor, genero, ano, isbn, local, sinopse, palavras,
                               total, disponiveis, tom, especial, popularidade)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 12)""",
        (dados["titulo"].strip(), dados["autor"].strip(), dados["genero"].strip(), ano or None,
         (dados.get("isbn") or "").strip(), (dados.get("local") or "").strip() or "Estante A-1",
         (dados.get("sinopse") or "").strip(), palavras, qtd, qtd, tom,
         1 if dados.get("especial") else 0))
    db.commit()
    return cur.lastrowid, None


def salvar_pessoa(db, dados: dict, pessoa_id=None):
    """UC11: inclui ou altera um usuário. Devolve (id, None) ou (None, erro)."""
    nome = (dados.get("nome") or "").strip()
    email = (dados.get("email") or "").strip().lower()
    matricula = (dados.get("matricula") or "").strip()
    tipo = dados.get("tipo")
    if not nome or not email or not matricula:
        return None, "Nome, e-mail e matrícula são obrigatórios."
    if "@" not in email:
        return None, "Informe um e-mail válido."
    if tipo not in TIPOS:
        return None, "Tipo de usuário inválido."
    ativo = 1 if dados.get("ativo") else 0
    try:
        if pessoa_id:
            db.execute("""UPDATE pessoas SET nome=?, email=?, telefone=?, tipo=?, matricula=?, ativo=?
                          WHERE id=?""", (nome, email, dados.get("telefone", ""), tipo, matricula, ativo, pessoa_id))
        else:
            cur = db.execute("""INSERT INTO pessoas (nome, email, telefone, tipo, matricula, ativo, desde)
                                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                             (nome, email, dados.get("telefone", ""), tipo, matricula, ativo, _iso(hoje())))
            pessoa_id = cur.lastrowid
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return None, "Já existe um usuário com este e-mail ou matrícula."
    return pessoa_id, None


def alternar_ativo(db, pessoa_id):
    db.execute("UPDATE pessoas SET ativo = 1 - ativo WHERE id = ?", (pessoa_id,))
    db.commit()


def remover_pessoa(db, pessoa_id):
    """UC11 (fluxo alternativo): não remove quem tem empréstimo ativo."""
    p = pessoa(db, pessoa_id)
    if p is None:
        return "Usuário não encontrado."
    if emprestimos_ativos(db, pessoa_id):
        return f"{p['nome']} ainda tem empréstimos em andamento."
    if db.execute("SELECT 1 FROM emprestimos WHERE pessoa_id = ?", (pessoa_id,)).fetchone():
        return f"{p['nome']} tem histórico de empréstimos; inative o cadastro em vez de remover."
    db.execute("DELETE FROM reservas WHERE pessoa_id = ?", (pessoa_id,))
    db.execute("DELETE FROM pessoas WHERE id = ?", (pessoa_id,))
    db.commit()
    return None


# --------------------------------------------------------------------- indicadores
def indicadores(db) -> dict:
    """UC02: números do painel inicial, calculados com os dados reais."""
    d = _iso(hoje())
    um = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    ativos = um("SELECT COUNT(*) FROM emprestimos WHERE devolvido IS NULL")
    atrasados = um("SELECT COUNT(*) FROM emprestimos WHERE devolvido IS NULL AND previsto < ?", d)
    return {
        "acervo": um("SELECT COALESCE(SUM(total),0) FROM livros"),
        "titulos": um("SELECT COUNT(*) FROM livros"),
        "emprestimos": ativos,
        "atrasados": atrasados,
        "leitores": um("SELECT COUNT(*) FROM pessoas WHERE ativo = 1"),
        "no_prazo": 100 if ativos == 0 else round(100 * (ativos - atrasados) / ativos),
        "reservas": um("SELECT COUNT(*) FROM reservas WHERE estado IN ('AGUARDANDO','PRONTA')"),
    }


def devolucoes_hoje(db):
    return db.execute(EMP_SQL + " WHERE e.devolvido IS NULL AND e.previsto <= ? ORDER BY e.previsto",
                      (_iso(hoje()),)).fetchall()


def relatorios(db) -> dict:
    """UC15: dados dos gráficos."""
    por_mes = db.execute("""SELECT substr(retirada, 1, 7) AS mes, COUNT(*) AS n FROM emprestimos
                            GROUP BY mes ORDER BY mes DESC LIMIT 6""").fetchall()[::-1]
    por_genero = db.execute("""SELECT genero, SUM(total) AS n FROM livros
                               GROUP BY genero ORDER BY n DESC""").fetchall()
    mais_emprestados = db.execute("""SELECT l.titulo, l.autor, COUNT(e.id) AS n FROM emprestimos e
                                     JOIN livros l ON l.id = e.livro_id GROUP BY l.id
                                     ORDER BY n DESC, l.titulo LIMIT 5""").fetchall()
    leitores = db.execute("""SELECT p.nome, p.tipo, COUNT(e.id) AS n FROM emprestimos e
                             JOIN pessoas p ON p.id = e.pessoa_id GROUP BY p.id
                             ORDER BY n DESC, p.nome LIMIT 5""").fetchall()
    return {"por_mes": por_mes, "por_genero": por_genero,
            "mais_emprestados": mais_emprestados, "leitores": leitores}
