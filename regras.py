"""Regras de negócio do Alexandria.

São as mesmas regras da classe Biblioteca.java da versão desktop, agora
usando o banco SQLite. Todas as funções de operação seguem o mesmo padrão:
se der tudo certo devolvem None; se não der, devolvem uma frase explicando
o motivo, e essa frase aparece direto para o usuário.
"""
import sqlite3
from datetime import date, timedelta

LIMITE_RENOVACOES = 2
TIPOS = ["Estudante", "Professor", "Funcionário", "Bibliotecário", "Administrador"]
TONS = ["GOLD", "CRIMSON", "BLUE", "FOREST", "PURPLE", "NOIR"]
POR_PAGINA = 8


def hoje() -> date:
    """Devolve a data de hoje. Ficou numa função separada para ser fácil de trocar nos testes."""
    return date.today()


def limite_emprestimos(tipo: str) -> int:
    """Estudante pode ter até 3 livros ao mesmo tempo; professor e equipe, até 5."""
    return 3 if tipo == "Estudante" else 5


def prazo_padrao(tipo: str) -> int:
    """Estudante tem 14 dias para devolver; os outros tipos têm 21."""
    return 14 if tipo == "Estudante" else 21


def eh_leitor(tipo: str) -> bool:
    """Só estudante e professor entram no sistema como leitor."""
    return tipo in ("Estudante", "Professor")


def _iso(d) -> str:
    """Converte a data para texto no formato do banco (AAAA-MM-DD)."""
    return d.isoformat() if isinstance(d, date) else str(d)


# --------------------------------------------------------------------- consultas
def livro(db, livro_id):
    """Busca um livro pelo id. Se não existir, devolve None."""
    return db.execute("SELECT * FROM livros WHERE id = ?", (livro_id,)).fetchone()


def pessoa(db, pessoa_id):
    """Busca uma pessoa pelo id. Se não existir, devolve None."""
    return db.execute("SELECT * FROM pessoas WHERE id = ?", (pessoa_id,)).fetchone()


def generos(db) -> list:
    """Lista de gêneros que existem no acervo, para os filtros e o cadastro."""
    return [r[0] for r in db.execute("SELECT DISTINCT genero FROM livros ORDER BY genero")]


def catalogo(db, busca="", genero="", disponibilidade="", ordem="titulo", pagina=1):
    """Busca do catálogo (UC03).

    Monta o SQL aos poucos conforme os filtros escolhidos. Os valores digitados
    vão sempre como parâmetro (?), nunca colados no SQL, para evitar injeção.
    Devolve os livros da página, o total encontrado, a página atual e o total de páginas.
    """
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
    """Empréstimos que ainda não voltaram (de todo mundo ou de uma pessoa), começando pelo que vence primeiro."""
    sql, args = EMP_SQL + " WHERE e.devolvido IS NULL", []
    if pessoa_id:
        sql += " AND e.pessoa_id = ?"
        args.append(pessoa_id)
    return db.execute(sql + " ORDER BY e.previsto", args).fetchall()


def historico(db, pessoa_id):
    """Tudo o que a pessoa já pegou emprestado, do mais novo para o mais antigo."""
    return db.execute(EMP_SQL + " WHERE e.pessoa_id = ? ORDER BY e.retirada DESC", (pessoa_id,)).fetchall()


def ids_lidos(db, pessoa_id) -> list:
    """Ids dos livros que a pessoa já pegou. É com isso que a IA monta o gosto do leitor."""
    return [r[0] for r in db.execute(
        "SELECT DISTINCT livro_id FROM emprestimos WHERE pessoa_id = ?", (pessoa_id,))]


def reservas(db, pessoa_id=None, so_abertas=False):
    """Lista as reservas com o nome do livro e do leitor. Dá para filtrar por pessoa e mostrar só as abertas."""
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
    """Quantos exemplares estão guardados para reservas PRONTAS de outras pessoas."""
    return db.execute("""SELECT COUNT(*) FROM reservas WHERE livro_id = ? AND estado = 'PRONTA'
                          AND pessoa_id <> ?""", (livro_id, pessoa_id)).fetchone()[0]


def atrasado(emp, dia=None) -> bool:
    """Diz se o empréstimo ainda não voltou e já passou da data de devolução."""
    return emp["devolvido"] is None and emp["previsto"] < _iso(dia or hoje())


def status_emprestimo(emp, dia=None) -> str:
    """Texto que aparece na tela: "Devolvido", "Atrasado" ou "No prazo"."""
    if emp["devolvido"]:
        return "Devolvido"
    return "Atrasado" if atrasado(emp, dia) else "No prazo"


# --------------------------------------------------------------------- operações
def emprestar(db, livro_id, pessoa_id, retirada=None, previsto=None):
    """Registra um empréstimo (UC06).

    Antes de gravar, confere tudo: se o livro e o leitor existem, se o leitor está
    ativo, se tem exemplar livre (e que não esteja guardado para a reserva de outra
    pessoa), se o leitor não tem nada atrasado e se ainda não chegou no limite.
    """
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
        # se a pessoa tinha reservado esse livro, a reserva dela foi atendida
        db.execute("""UPDATE reservas SET estado = 'ATENDIDA'
                       WHERE livro_id = ? AND pessoa_id = ? AND estado IN ('AGUARDANDO','PRONTA')""",
                   (l["id"], p["id"]))
        db.commit()
    except sqlite3.Error as erro:
        db.rollback()
        return f"Não foi possível registrar: {erro}"
    return None


def devolver(db, emprestimo_id):
    """Registra a devolução (UC07).

    O exemplar volta para o estoque e, se alguém estiver esperando esse livro,
    a reserva mais antiga passa para PRONTA.
    """
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
    """Renova o empréstimo (UC08).

    Pode renovar no máximo 2 vezes e não pode se tiver alguém na fila esperando
    o livro. Se já estiver atrasado, o novo prazo conta a partir de hoje.
    """
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
    """Cria uma reserva (UC09).

    Só faz sentido reservar livro que não tem exemplar livre, então se tiver,
    a gente avisa para fazer o empréstimo direto.
    """
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
    """Cancela uma reserva (UC10).

    Quando o pessoa_id vem preenchido (leitor logado), só deixa cancelar as reservas
    dele. Se a reserva cancelada estava PRONTA, o livro passa para o próximo da fila.
    """
    r = db.execute("SELECT * FROM reservas WHERE id = ?", (reserva_id,)).fetchone()
    if r is None or (pessoa_id and r["pessoa_id"] != pessoa_id):
        return "Reserva não encontrada."
    if r["estado"] not in ("AGUARDANDO", "PRONTA"):
        return "Só reservas ativas podem ser canceladas."
    db.execute("UPDATE reservas SET estado = 'CANCELADA' WHERE id = ?", (r["id"],))
    if r["estado"] == "PRONTA":
        # o livro que estava guardado para essa pessoa passa para o próximo da fila
        prox = db.execute("""SELECT id FROM reservas WHERE livro_id = ? AND estado = 'AGUARDANDO'
                             ORDER BY data, id LIMIT 1""", (r["livro_id"],)).fetchone()
        if prox:
            db.execute("UPDATE reservas SET estado = 'PRONTA' WHERE id = ?", (prox["id"],))
    db.commit()
    return None


def cadastrar_livro(db, dados: dict):
    """Valida e grava um livro novo (UC05).

    Título, autor e gênero são obrigatórios. Se as palavras-chave ficarem em branco,
    usamos o gênero e a sinopse no lugar, para a IA ter alguma coisa com o que trabalhar.
    Devolve (id, None) se deu certo ou (None, mensagem de erro).
    """
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
    """Cria ou edita um usuário (UC11).

    Se vier pessoa_id, é edição; se não, é cadastro novo. E-mail e matrícula
    não podem se repetir, e o próprio banco garante isso (UNIQUE).
    Devolve (id, None) se deu certo ou (None, mensagem de erro).
    """
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
    """Ativa quem está inativo e inativa quem está ativo."""
    db.execute("UPDATE pessoas SET ativo = 1 - ativo WHERE id = ?", (pessoa_id,))
    db.commit()


def remover_pessoa(db, pessoa_id):
    """Remove um usuário (UC11).

    Não deixa remover quem está com livro emprestado. Quem já teve empréstimo
    também não pode ser apagado, para não perder o histórico; nesse caso o certo é inativar.
    """
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
    """Os números do painel inicial (UC02), calculados direto do banco."""
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
    """Empréstimos que vencem hoje ou que já estão atrasados."""
    return db.execute(EMP_SQL + " WHERE e.devolvido IS NULL AND e.previsto <= ? ORDER BY e.previsto",
                      (_iso(hoje()),)).fetchall()


def relatorios(db) -> dict:
    """Os dados dos gráficos da tela de relatórios (UC15)."""
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
