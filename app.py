"""Alexandria Web - arquivo principal.

Aqui ficam as rotas do Flask: cada função recebe o pedido do navegador,
chama as regras de negócio (regras.py) ou a IA (ia.py) e devolve a página pronta.

Para rodar: python app.py e abrir http://127.0.0.1:5000 no navegador.
"""
import csv
import io
import os
import secrets
from datetime import date
from functools import wraps
from hmac import compare_digest

from flask import (Flask, Response, abort, flash, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash

import banco
import regras
from ia import MotorIA

PERGUNTAS_SUGERIDAS = ["distopia e poder", "aprender a programar", "aventura e fantasia",
                       "filosofia e ética", "universo e ciência", "amor e ciúme"]


def criar_app(config: dict | None = None) -> Flask:
    """Monta a aplicação: chave da sessão, caminho do banco e todas as rotas."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(
        SECRET_KEY=os.environ.get("ALEXANDRIA_CHAVE") or secrets.token_hex(32),
        BANCO=os.path.join(app.instance_path, "alexandria.db"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if config:
        app.config.update(config)
    banco.iniciar_app(app)
    registrar_rotas(app)
    return app


# ============================================================ segurança / sessão
def login_obrigatorio(perfil=None):
    """Decorador que protege as páginas.

    Quem não estiver logado volta para o login. Se a página for só da equipe,
    o leitor recebe erro 403 em vez de conseguir entrar pelo endereço.
    """
    def deco(fn):
        """Recebe a função da rota e devolve ela já "embrulhada" com a verificação."""
        @wraps(fn)
        def interno(*a, **kw):
            """É o que roda de verdade a cada acesso: confere login, conta ativa e perfil."""
            if "perfil" not in session:
                return redirect(url_for("login", proximo=request.path))
            # a conta pode ter sido inativada (ou apagada) depois que a pessoa entrou
            tabela = "funcionarios" if session["perfil"] == "equipe" else "pessoas"
            conta = banco.get_db().execute(f"SELECT ativo FROM {tabela} WHERE id = ?", (session.get("id"),)).fetchone()
            if conta is None or not conta["ativo"]:
                session.clear()
                flash("Sua conta está inativa. Procure a biblioteca.", "erro")
                return redirect(url_for("login"))
            if perfil and session["perfil"] != perfil:
                abort(403)
            return fn(*a, **kw)
        return interno
    return deco


def token_csrf() -> str:
    """Pega o token de segurança da sessão (ou cria um, se for o primeiro acesso)."""
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def checar_csrf():
    """Roda antes de todo POST.

    Se o formulário não trouxer o mesmo token que está na sessão, a gente recusa.
    Isso impede que outro site envie formulários em nome do usuário (ataque CSRF).
    """
    if request.method == "POST":
        enviado = request.form.get("csrf", "")
        esperado = session.get("csrf", "")
        if not esperado or not iguais(enviado, esperado):
            abort(400, "Formulário expirado. Recarregue a página.")


def iguais(a: str, b: str) -> bool:
    """Compara dois textos sem deixar o tempo da comparação "vazar" informação. Funciona com acento."""
    return compare_digest((a or "").encode("utf-8"), (b or "").encode("utf-8"))


def destino_seguro(url, padrao):
    """Só deixa redirecionar para páginas do próprio sistema, nunca para um site de fora."""
    if url and url.startswith(request.host_url):
        url = url[len(request.host_url) - 1:]
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return padrao


def voltar(padrao_endpoint):
    """Volta para a página de onde o usuário veio (ou para a página padrão, se não der)."""
    return redirect(destino_seguro(request.referrer, url_for(padrao_endpoint)))


def motor(db) -> MotorIA:
    """Cria o motor de IA com os livros que estão no banco agora."""
    livros = [dict(r) for r in db.execute("SELECT * FROM livros ORDER BY id")]
    return MotorIA(livros)


def resultado(erro, sucesso):
    """Mostra a mensagem certa na tela: vermelha se deu erro, verde se deu certo."""
    flash(erro or sucesso, "erro" if erro else "ok")


def para_data(texto):
    """Transforma a data que vem do formulário (AAAA-MM-DD) em data do Python. Se vier vazia ou errada, devolve None."""
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        return None


# ============================================================ rotas
def registrar_rotas(app: Flask) -> None:
    """Cadastra todas as páginas do sistema no Flask."""
    app.before_request(checar_csrf)

    @app.context_processor
    def globais():
        """Coisas que todas as páginas usam: nome de quem está logado, perfil, token do formulário..."""
        return {"csrf": token_csrf(), "usuario": session.get("nome"), "perfil": session.get("perfil"),
                "cargo": session.get("cargo"), "status_emp": regras.status_emprestimo, "hoje": regras.hoje()}

    @app.template_filter("br")
    def data_br(valor):
        """Mostra as datas no formato brasileiro (dd/mm/aaaa) nas páginas."""
        if not valor:
            return "—"
        a, m, d = str(valor)[:10].split("-")
        return f"{d}/{m}/{a}"

    # ---------------------------------------------------- UC01 / UC17 / UC16
    @app.route("/", methods=["GET", "POST"])
    @app.route("/login", methods=["GET", "POST"])
    def login():
        """Tela de login (UC01 e UC17).

        Primeiro tenta como funcionário (e-mail + senha). Se não for, tenta como
        leitor, que entra com o e-mail e usa a matrícula como senha.
        """
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            senha = request.form.get("senha", "")
            db = banco.get_db()
            f = db.execute("SELECT * FROM funcionarios WHERE lower(email) = ? AND ativo = 1", (email,)).fetchone()
            if f and check_password_hash(f["senha_hash"], senha):
                session.clear()
                session.update(perfil="equipe", id=f["id"], nome=f["nome"], cargo=f["cargo"])
                return redirect(destino_seguro(request.args.get("proximo"), url_for("inicio")))
            p = db.execute("SELECT * FROM pessoas WHERE lower(email) = ?", (email,)).fetchone()
            if p and regras.eh_leitor(p["tipo"]) and p["ativo"] and iguais(senha, p["matricula"]):
                session.clear()
                session.update(perfil="leitor", id=p["id"], nome=p["nome"], cargo=p["tipo"])
                return redirect(url_for("inicio"))
            flash("E-mail ou senha inválidos, ou cadastro inativo.", "erro")
        return render_template("login.html")

    @app.route("/sair")
    def sair():
        """Encerra a sessão e manda de volta para o login (UC16)."""
        session.clear()
        flash("Sessão encerrada.", "ok")
        return redirect(url_for("login"))

    # ---------------------------------------------------- UC02 / UC13 / UC14
    @app.route("/inicio")
    @login_obrigatorio()
    def inicio():
        """Página inicial (UC02, UC13 e UC14).

        A equipe vê os números da biblioteca e pode escolher de qual leitor quer ver as
        sugestões da IA. O leitor vê só as sugestões dele, os empréstimos e as reservas.
        """
        db = banco.get_db()
        leitores = db.execute("""SELECT id, nome FROM pessoas WHERE tipo IN ('Estudante','Professor')
                                 AND ativo = 1 ORDER BY nome""").fetchall()
        if session["perfil"] == "leitor":
            leitor_id = session["id"]           # leitor só vê as sugestões dele
        else:
            leitor_id = request.args.get("leitor", type=int) or (leitores[0]["id"] if leitores else None)
        pergunta = request.args.get("pergunta", "").strip()
        ia = motor(db)
        if pergunta:
            recs = ia.buscar_por_texto(pergunta)
            entendidos = ia.termos_reconhecidos(pergunta)
        else:
            recs = ia.recomendar_para_leitor(regras.ids_lidos(db, leitor_id)) if leitor_id else ia.mais_procuradas()
            entendidos = []
        ctx = dict(leitores=leitores, leitor_id=leitor_id, pergunta=pergunta, recs=recs,
                   entendidos=entendidos, sugestoes=PERGUNTAS_SUGERIDAS)
        if session["perfil"] == "equipe":
            ctx.update(kpi=regras.indicadores(db), devolucoes=regras.devolucoes_hoje(db))
        else:
            ctx.update(meus=regras.emprestimos_ativos(db, session["id"]),
                       minhas_res=regras.reservas(db, session["id"], so_abertas=True))
        return render_template("inicio.html", **ctx)

    # ---------------------------------------------------- UC03 / UC04
    @app.route("/catalogo")
    @login_obrigatorio()
    def catalogo():
        """Catálogo de livros com busca, filtros, ordem, visão em grade ou lista e 8 livros por página (UC03)."""
        db = banco.get_db()
        f = {k: request.args.get(k, "") for k in ("busca", "genero", "disp", "ordem")}
        livros, total, pagina, paginas = regras.catalogo(
            db, f["busca"].strip(), f["genero"], f["disp"], f["ordem"] or "titulo",
            request.args.get("pagina", 1, type=int))
        return render_template("catalogo.html", livros=livros, total=total, pagina=pagina,
                               paginas=paginas, generos=regras.generos(db), f=f,
                               visao=request.args.get("visao", "grade"))

    @app.route("/livro/<int:livro_id>")
    @login_obrigatorio()
    def detalhe(livro_id):
        """Página de um livro: dados completos, fila de reservas e livros parecidos indicados pela IA (UC04)."""
        db = banco.get_db()
        l = regras.livro(db, livro_id) or abort(404)
        fila = db.execute("SELECT COUNT(*) FROM reservas WHERE livro_id = ? AND estado = 'AGUARDANDO'",
                          (livro_id,)).fetchone()[0]
        parecidos = [r for r in motor(db).recomendar_para_leitor([livro_id], 4)]
        leitores = db.execute("""SELECT id, nome, tipo FROM pessoas WHERE ativo = 1
                                 ORDER BY nome""").fetchall()
        ref = destino_seguro(request.referrer, "")
        voltar_url = ref if ref.startswith("/catalogo") else url_for("catalogo")
        return render_template("livro.html", l=l, fila=fila, parecidos=parecidos, leitores=leitores,
                               voltar_url=voltar_url)

    # ---------------------------------------------------- UC06 / UC07 / UC08
    @app.route("/emprestimos", methods=["GET", "POST"])
    @login_obrigatorio("equipe")
    def emprestimos():
        """Tela de empréstimos: o formulário para emprestar e a lista do que ainda não voltou (UC06)."""
        db = banco.get_db()
        if request.method == "POST":
            erro = regras.emprestar(db, request.form.get("livro", type=int), request.form.get("pessoa", type=int),
                                    para_data(request.form.get("retirada")), para_data(request.form.get("previsto")))
            resultado(erro, "Empréstimo registrado.")
            return redirect(url_for("emprestimos"))
        filtro = request.args.get("filtro", "")
        ativos = regras.emprestimos_ativos(db)
        if filtro == "atrasados":
            ativos = [e for e in ativos if regras.atrasado(e)]
        return render_template(
            "emprestimos.html", ativos=ativos, filtro=filtro,
            leitores=db.execute("SELECT id, nome, tipo, matricula FROM pessoas WHERE ativo = 1 ORDER BY nome").fetchall(),
            livros=db.execute("SELECT id, titulo, autor FROM livros WHERE disponiveis > 0 ORDER BY titulo").fetchall(),
            livro_sel=request.args.get("livro", type=int), pessoa_sel=request.args.get("pessoa", type=int),
            recentes=db.execute(regras.EMP_SQL + " WHERE e.devolvido IS NOT NULL ORDER BY e.devolvido DESC LIMIT 6").fetchall())

    @app.post("/emprestimos/<int:emp_id>/devolver")
    @login_obrigatorio("equipe")
    def devolver(emp_id):
        """Botão "Devolver" da lista de empréstimos (UC07)."""
        resultado(regras.devolver(banco.get_db(), emp_id), "Devolução registrada.")
        return voltar("emprestimos")

    @app.post("/emprestimos/<int:emp_id>/renovar")
    @login_obrigatorio("equipe")
    def renovar(emp_id):
        """Botão "Renovar". As regras (máximo de 2 vezes etc.) ficam em regras.renovar (UC08)."""
        resultado(regras.renovar(banco.get_db(), emp_id), "Empréstimo renovado.")
        return voltar("emprestimos")

    # ---------------------------------------------------- UC09 / UC10
    @app.route("/reservas", methods=["GET", "POST"])
    @login_obrigatorio()
    def reservas():
        """Tela de reservas (UC09). O leitor só enxerga e cria reservas no próprio nome."""
        db = banco.get_db()
        leitor = session["perfil"] == "leitor"
        if request.method == "POST":
            pessoa_id = session["id"] if leitor else request.form.get("pessoa", type=int)
            erro = regras.reservar(db, request.form.get("livro", type=int), pessoa_id)
            resultado(erro, "Reserva registrada.")
            return voltar("reservas")
        return render_template(
            "reservas.html",
            reservas=regras.reservas(db, session["id"] if leitor else None),
            livros=db.execute("SELECT id, titulo, disponiveis FROM livros ORDER BY titulo").fetchall(),
            leitores=[] if leitor else db.execute(
                "SELECT id, nome FROM pessoas WHERE ativo = 1 ORDER BY nome").fetchall())

    @app.post("/reservas/<int:res_id>/cancelar")
    @login_obrigatorio()
    def cancelar_reserva(res_id):
        """Cancela uma reserva (UC10). Se for leitor, só consegue cancelar as dele."""
        dono = session["id"] if session["perfil"] == "leitor" else None
        resultado(regras.cancelar_reserva(banco.get_db(), res_id, dono), "Reserva cancelada.")
        return voltar("reservas")

    # ---------------------------------------------------- UC05
    @app.route("/acervo", methods=["GET", "POST"])
    @login_obrigatorio("equipe")
    def acervo():
        """Cadastro de livro novo (UC05). Se faltar algum campo, a tela volta com o que já foi digitado."""
        db = banco.get_db()
        dados = {}
        if request.method == "POST":
            dados = request.form.to_dict()
            novo_id, erro = regras.cadastrar_livro(db, dados)
            if not erro:
                flash("Obra cadastrada no acervo.", "ok")
                return redirect(url_for("detalhe", livro_id=novo_id))
            flash(erro, "erro")
        return render_template("acervo.html", d=dados, generos=regras.generos(db), tons=regras.TONS,
                               recentes=db.execute("SELECT * FROM livros ORDER BY id DESC LIMIT 5").fetchall())

    # ---------------------------------------------------- UC11 / UC12
    @app.route("/usuarios", methods=["GET", "POST"])
    @login_obrigatorio("equipe")
    def usuarios():
        """Tela de usuários (UC11): lista com busca e o painel do lado para incluir ou editar."""
        db = banco.get_db()
        if request.method == "POST":
            pid, erro = regras.salvar_pessoa(db, request.form.to_dict(), request.form.get("id", type=int))
            resultado(erro, "Usuário salvo.")
            return redirect(url_for("usuarios", ver=pid) if pid else url_for("usuarios"))
        busca, tipo = request.args.get("busca", "").strip(), request.args.get("tipo", "")
        sql = """SELECT p.*, (SELECT COUNT(*) FROM emprestimos e WHERE e.pessoa_id = p.id
                 AND e.devolvido IS NULL) AS ativos FROM pessoas p WHERE 1=1"""
        args = []
        if busca:
            sql += " AND (p.nome LIKE ? OR p.email LIKE ? OR p.matricula LIKE ?)"
            args += [f"%{busca}%"] * 3
        if tipo:
            sql += " AND p.tipo = ?"
            args.append(tipo)
        ver = request.args.get("ver", type=int)
        sel = regras.pessoa(db, ver) if ver else None
        return render_template("usuarios.html", pessoas=db.execute(sql + " ORDER BY p.nome", args).fetchall(),
                               busca=busca, tipo=tipo, tipos=regras.TIPOS, sel=sel,
                               novo=request.args.get("novo"),
                               hist=regras.historico(db, ver) if sel else [])

    @app.post("/usuarios/<int:pid>/ativo")
    @login_obrigatorio("equipe")
    def alternar_ativo(pid):
        """Botão "Ativar/Inativar" do cadastro."""
        regras.alternar_ativo(banco.get_db(), pid)
        flash("Situação do cadastro alterada.", "ok")
        return redirect(url_for("usuarios", ver=pid))

    @app.post("/usuarios/<int:pid>/remover")
    @login_obrigatorio("equipe")
    def remover(pid):
        """Botão "Remover". Não deixa apagar quem tem empréstimo; nesse caso o certo é inativar."""
        erro = regras.remover_pessoa(banco.get_db(), pid)
        resultado(erro, "Usuário removido.")
        return redirect(url_for("usuarios", ver=pid) if erro else url_for("usuarios"))

    @app.route("/usuarios.csv")
    @login_obrigatorio("equipe")
    def exportar_csv():
        """Baixa a lista de usuários em CSV para abrir no Excel (UC12).

        Usa ponto e vírgula e o caractere BOM no começo, senão o Excel em português
        bagunça as colunas e os acentos.
        """
        saida = io.StringIO()
        w = csv.writer(saida, delimiter=";")
        w.writerow(["id", "nome", "email", "telefone", "tipo", "matricula", "ativo", "desde"])
        def celula(v):
            """Se o texto começar com = + - ou @, coloca um apóstrofo antes para o Excel não tratar como fórmula."""
            v = "" if v is None else str(v)
            return "'" + v if v[:1] in ("=", "+", "-", "@") else v
        for p in banco.get_db().execute("SELECT * FROM pessoas ORDER BY nome"):
            w.writerow([celula(x) for x in (p["id"], p["nome"], p["email"], p["telefone"], p["tipo"],
                                            p["matricula"], "sim" if p["ativo"] else "não", p["desde"])])
        return Response("\ufeff" + saida.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=usuarios_alexandria.csv"})

    # ---------------------------------------------------- UC15
    @app.route("/relatorios")
    @login_obrigatorio("equipe")
    def relatorios():
        """Página de relatórios com os indicadores e os gráficos de barras (UC15)."""
        db = banco.get_db()
        return render_template("relatorios.html", r=regras.relatorios(db), kpi=regras.indicadores(db))

    @app.errorhandler(400)
    def requisicao_invalida(_e):
        """Quando o formulário expira (ex.: o servidor reiniciou), avisa e volta em vez de mostrar um erro feio."""
        flash("O formulário expirou. Tente de novo.", "erro")
        return redirect(destino_seguro(request.referrer, url_for("login")))

    @app.errorhandler(403)
    def proibido(_e):
        """Erro 403: o perfil não pode abrir essa página."""
        return render_template("erro.html", codigo=403, msg="Seu perfil não tem acesso a esta página."), 403

    @app.errorhandler(404)
    def nao_achou(_e):
        """Erro 404: a página não existe."""
        return render_template("erro.html", codigo=404, msg="Página não encontrada."), 404


app = criar_app()

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
