"""
Testes automatizados do Alexandria Web.
Executar na pasta do projeto:  python -m unittest discover -s testes -v
"""
import os
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import banco      # noqa: E402
import regras     # noqa: E402
from app import criar_app  # noqa: E402
from ia import MotorIA     # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho = os.path.join(self.tmp.name, "teste.db")
        banco.criar_banco(self.caminho)
        self.db = banco.conectar(self.caminho)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def novo_livro(self, qtd=1):
        lid, erro = regras.cadastrar_livro(self.db, {"titulo": "Livro Teste", "autor": "Autora X",
                                                     "genero": "Teste", "quantidade": qtd})
        self.assertIsNone(erro)
        return lid

    def nova_pessoa(self, tipo="Estudante", mat="T001"):
        pid, erro = regras.salvar_pessoa(self.db, {"nome": "Pessoa " + mat, "email": mat + "@t.br",
                                                   "tipo": tipo, "matricula": mat, "ativo": "1"})
        self.assertIsNone(erro)
        return pid


class TestRegras(Base):
    def test_emprestimo_reduz_exemplares_e_aumenta_popularidade(self):
        lid, pid = self.novo_livro(2), self.nova_pessoa()
        antes = regras.livro(self.db, lid)
        self.assertIsNone(regras.emprestar(self.db, lid, pid))
        depois = regras.livro(self.db, lid)
        self.assertEqual(depois["disponiveis"], antes["disponiveis"] - 1)
        self.assertEqual(depois["popularidade"], antes["popularidade"] + 1)

    def test_prazo_padrao_estudante_14_e_professor_21(self):
        lid = self.novo_livro(2)
        est, prof = self.nova_pessoa("Estudante", "E1"), self.nova_pessoa("Professor", "P1")
        regras.emprestar(self.db, lid, est)
        regras.emprestar(self.db, lid, prof)
        prazos = {e["tipo"]: e["previsto"] for e in regras.emprestimos_ativos(self.db) if e["livro_id"] == lid}
        self.assertEqual(prazos["Estudante"], (date.today() + timedelta(days=14)).isoformat())
        self.assertEqual(prazos["Professor"], (date.today() + timedelta(days=21)).isoformat())

    def test_limite_de_3_emprestimos_para_estudante(self):
        pid = self.nova_pessoa()
        for _ in range(3):
            self.assertIsNone(regras.emprestar(self.db, self.novo_livro(), pid))
        erro = regras.emprestar(self.db, self.novo_livro(), pid)
        self.assertIn("limite de 3", erro)

    def test_livro_sem_exemplar_e_leitor_inativo_sao_recusados(self):
        lid = self.novo_livro(1)
        a, b = self.nova_pessoa(mat="A1"), self.nova_pessoa(mat="B1")
        regras.emprestar(self.db, lid, a)
        self.assertIn("sem exemplares", regras.emprestar(self.db, lid, b))
        regras.alternar_ativo(self.db, b)
        self.assertIn("inativo", regras.emprestar(self.db, self.novo_livro(), b))

    def test_devolucao_libera_exemplar_e_reserva_fica_pronta(self):
        lid = self.novo_livro(1)
        a, b = self.nova_pessoa(mat="A1"), self.nova_pessoa(mat="B1")
        regras.emprestar(self.db, lid, a)
        self.assertIsNone(regras.reservar(self.db, lid, b))
        emp = regras.emprestimos_ativos(self.db, a)[0]
        self.assertIsNone(regras.devolver(self.db, emp["id"]))
        self.assertEqual(regras.livro(self.db, lid)["disponiveis"], 1)
        self.assertEqual(regras.reservas(self.db, b)[0]["estado"], "PRONTA")
        # quando o leitor da reserva retira o livro, a reserva vira ATENDIDA
        regras.emprestar(self.db, lid, b)
        self.assertEqual(regras.reservas(self.db, b)[0]["estado"], "ATENDIDA")

    def test_no_maximo_duas_renovacoes(self):
        lid, pid = self.novo_livro(), self.nova_pessoa()
        regras.emprestar(self.db, lid, pid)
        emp = regras.emprestimos_ativos(self.db, pid)[0]
        self.assertIsNone(regras.renovar(self.db, emp["id"]))
        self.assertIsNone(regras.renovar(self.db, emp["id"]))
        self.assertIn("Limite de 2", regras.renovar(self.db, emp["id"]))

    def test_nao_renova_com_reserva_aguardando(self):
        lid = self.novo_livro(1)
        a, b = self.nova_pessoa(mat="A1"), self.nova_pessoa(mat="B1")
        regras.emprestar(self.db, lid, a)
        regras.reservar(self.db, lid, b)
        emp = regras.emprestimos_ativos(self.db, a)[0]
        self.assertIn("reserva aguardando", regras.renovar(self.db, emp["id"]))

    def test_reserva_duplicada_e_cancelamento(self):
        lid, pid = self.novo_livro(), self.nova_pessoa()
        regras.emprestar(self.db, lid, self.nova_pessoa(mat="X9"))   # deixa o livro indisponível
        self.assertIsNone(regras.reservar(self.db, lid, pid))
        self.assertIn("já existe", regras.reservar(self.db, lid, pid))
        r = regras.reservas(self.db, pid)[0]
        self.assertIsNone(regras.cancelar_reserva(self.db, r["id"]))
        self.assertEqual(regras.reservas(self.db, pid)[0]["estado"], "CANCELADA")

    def test_exemplar_separado_para_reserva_pronta(self):
        lid = self.novo_livro(1)
        a, b, c = self.nova_pessoa(mat="A1"), self.nova_pessoa(mat="B1"), self.nova_pessoa(mat="C1")
        regras.emprestar(self.db, lid, a)
        regras.reservar(self.db, lid, b)
        regras.devolver(self.db, regras.emprestimos_ativos(self.db, a)[0]["id"])
        self.assertIn("separado", regras.emprestar(self.db, lid, c))   # outro leitor não leva
        self.assertIsNone(regras.emprestar(self.db, lid, b))           # quem reservou leva

    def test_cancelar_reserva_pronta_passa_para_o_proximo(self):
        lid = self.novo_livro(1)
        a, b, c = self.nova_pessoa(mat="A1"), self.nova_pessoa(mat="B1"), self.nova_pessoa(mat="C1")
        regras.emprestar(self.db, lid, a)
        regras.reservar(self.db, lid, b)
        regras.reservar(self.db, lid, c)
        regras.devolver(self.db, regras.emprestimos_ativos(self.db, a)[0]["id"])
        regras.cancelar_reserva(self.db, regras.reservas(self.db, b)[0]["id"])
        self.assertEqual(regras.reservas(self.db, c)[0]["estado"], "PRONTA")

    def test_nao_reserva_livro_disponivel_nem_o_que_ja_esta_com_a_pessoa(self):
        lid, pid = self.novo_livro(2), self.nova_pessoa()
        self.assertIn("disponível", regras.reservar(self.db, lid, pid))
        outro = self.novo_livro(1)
        regras.emprestar(self.db, outro, pid)
        self.assertIn("já está com este livro", regras.reservar(self.db, outro, pid))

    def test_nao_remove_usuario_com_emprestimo_ativo(self):
        lid, pid = self.novo_livro(), self.nova_pessoa()
        regras.emprestar(self.db, lid, pid)
        self.assertIn("em andamento", regras.remover_pessoa(self.db, pid))
        sem_historico = self.nova_pessoa(mat="Z9")
        self.assertIsNone(regras.remover_pessoa(self.db, sem_historico))

    def test_cadastro_exige_campos_obrigatorios(self):
        _, erro = regras.cadastrar_livro(self.db, {"titulo": "", "autor": "X", "genero": ""})
        self.assertIn("Título", erro)
        self.assertIn("Gênero", erro)

    def test_email_ou_matricula_duplicados(self):
        self.nova_pessoa(mat="D1")
        _, erro = regras.salvar_pessoa(self.db, {"nome": "Outra", "email": "D1@t.br", "tipo": "Estudante",
                                                 "matricula": "D2", "ativo": "1"})
        self.assertIn("Já existe", erro)

    def test_catalogo_paginado_com_8_por_pagina(self):
        livros, total, pagina, paginas = regras.catalogo(self.db)
        self.assertEqual(len(livros), 8)
        self.assertEqual(paginas, -(-total // 8))


class TestIA(Base):
    def setUp(self):
        super().setUp()
        self.ia = MotorIA([dict(r) for r in self.db.execute("SELECT * FROM livros")])
        self.por_titulo = {l["titulo"]: l["id"] for l in self.ia.acervo}

    def test_leitor_de_orwell_recebe_distopias(self):
        recs = self.ia.recomendar_para_leitor([self.por_titulo["1984"]], 3)
        titulos = [r.livro["titulo"] for r in recs]
        self.assertIn("Fahrenheit 451", titulos)
        self.assertNotIn("1984", titulos)            # livro já lido não é sugerido
        self.assertTrue(all(0 <= r.afinidade < 1 for r in recs))

    def test_pergunta_em_linguagem_natural(self):
        recs = self.ia.buscar_por_texto("quero aprender a programar", 3)
        self.assertTrue(recs)
        self.assertTrue(all(r.livro["genero"] == "Tecnologia" for r in recs))

    def test_leitor_sem_historico_recebe_mais_procurados(self):
        recs = self.ia.recomendar_para_leitor([], 3)
        pops = [r.livro["popularidade"] for r in recs]
        self.assertEqual(pops, sorted(pops, reverse=True))


class TestWeb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = criar_app({"BANCO": os.path.join(self.tmp.name, "w.db"), "TESTING": True})
        self.c = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def csrf(self, url="/login"):
        html = self.c.get(url).get_data(as_text=True)
        return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)

    def entrar(self, email, senha):
        return self.c.post("/login", data={"email": email, "senha": senha, "csrf": self.csrf()},
                           follow_redirects=True)

    def test_paginas_exigem_login(self):
        r = self.c.get("/catalogo")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_login_invalido(self):
        r = self.entrar("augusto.bento@alexandria.com.br", "errada")
        self.assertIn("inválidos", r.get_data(as_text=True))

    def test_post_sem_token_csrf_e_recusado(self):
        r = self.c.post("/login", data={"email": "augusto.bento@alexandria.com.br", "senha": "Adm1958"},
                        follow_redirects=True)
        html = r.get_data(as_text=True)
        self.assertIn("formulário expirou", html)
        self.assertNotIn("Olá", html)              # não entrou no sistema

    def test_senha_com_acento_nao_derruba_o_servidor(self):
        r = self.entrar("ana.silva@aluno.edu.br", "ação")
        self.assertEqual(r.status_code, 200)
        self.assertIn("inválidos", r.get_data(as_text=True))

    def test_login_nao_redireciona_para_outro_site(self):
        token = self.csrf()
        r = self.c.post("/login?proximo=https://site-malicioso.com",
                        data={"email": "augusto.bento@alexandria.com.br", "senha": "Adm1958", "csrf": token})
        self.assertTrue(r.headers["Location"].endswith("/inicio"))

    def test_leitor_inativado_perde_o_acesso(self):
        self.entrar("ana.silva@aluno.edu.br", "2023001")
        db = banco.conectar(self.app.config["BANCO"])
        regras.alternar_ativo(db, 1)
        db.close()
        r = self.c.get("/reservas")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_csv_nao_exporta_formulas(self):
        db = banco.conectar(self.app.config["BANCO"])
        regras.salvar_pessoa(db, {"nome": "=1+1", "email": "f@f.br", "tipo": "Estudante",
                                  "matricula": "F1", "ativo": "1"})
        db.close()
        self.entrar("augusto.bento@alexandria.com.br", "Adm1958")
        csv = self.c.get("/usuarios.csv").get_data(as_text=True)
        self.assertIn("'=1+1", csv)

    def test_equipe_acessa_todas_as_telas(self):
        r = self.entrar("augusto.bento@alexandria.com.br", "Adm1958")
        self.assertIn("Augusto", r.get_data(as_text=True))
        for url in ["/inicio", "/catalogo", "/catalogo?visao=lista&genero=Romance", "/livro/4",
                    "/emprestimos", "/reservas", "/acervo", "/usuarios", "/usuarios?ver=1",
                    "/relatorios", "/inicio?pergunta=distopia", "/usuarios.csv"]:
            self.assertEqual(self.c.get(url).status_code, 200, url)

    def test_leitor_tem_menu_reduzido(self):
        r = self.entrar("ana.silva@aluno.edu.br", "2023001")
        html = r.get_data(as_text=True)
        self.assertIn("Meus empréstimos", html)
        self.assertNotIn(">Usuários<", html)
        for url in ["/emprestimos", "/acervo", "/usuarios", "/relatorios"]:
            self.assertEqual(self.c.get(url).status_code, 403, url)

    def test_fluxo_de_emprestimo_pela_web(self):
        self.entrar("karine.varela@alexandria.com.br", "Adm2608")
        token = self.csrf("/emprestimos")
        r = self.c.post("/emprestimos", data={"csrf": token, "livro": 5, "pessoa": 3,
                                              "retirada": date.today().isoformat(),
                                              "previsto": (date.today() + timedelta(days=21)).isoformat()},
                        follow_redirects=True)
        self.assertIn("Empréstimo registrado", r.get_data(as_text=True))

    def test_cadastro_de_livro_pela_web(self):
        self.entrar("karine.varela@alexandria.com.br", "Adm2608")
        r = self.c.post("/acervo", data={"csrf": self.csrf("/acervo"), "titulo": "Novo Livro",
                                         "autor": "Autor", "genero": "Romance", "quantidade": "2",
                                         "tom": "BLUE"}, follow_redirects=True)
        self.assertIn("Obra cadastrada", r.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
