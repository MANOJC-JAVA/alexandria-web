"""Motor de recomendação do Alexandria (a parte de Inteligência Artificial).

É a versão em Python do MotorRecomendacao.java do sistema desktop. Não usa
nenhuma biblioteca de fora nem internet. A ideia, resumindo:

 1. Cada livro vira um "documento" com o gênero (peso 2), o autor (peso 1,5)
    e as palavras-chave (peso 1).
 2. Esse texto é limpo (minúsculas, sem acento, sem palavras como "de" e "o",
    sem plural) e vira um vetor TF-IDF: termos que aparecem muito no livro e
    pouco no resto do acervo ganham mais peso.
 3. O gosto do leitor é a soma dos vetores dos livros que ele já pegou.
 4. A afinidade é a similaridade do cosseno entre o gosto do leitor e cada livro.
 5. Os termos em comum que mais pesaram viram a explicação mostrada na tela.
"""
import math
import re
import unicodedata
from dataclasses import dataclass

STOPWORDS = set("""
a o as os um uma uns umas de da do das dos e em no na nos nas que com por para pra ao aos
se sua seu suas seus ou mas como mais sobre quero algo livro livros ler gosto gostaria
preciso tem ter ser me eu meu minha queria procuro buscar indicar indica aprender et al
obra obras tipo coisa muito bem
""".split())

# Conceitos relacionados: ajudam a IA a entender perguntas escritas do jeito que a pessoa fala.
# Cada item é: (palavras que podem aparecer na pergunta, termos parecidos que existem no acervo)
CONCEITOS = [
    ("programar,programador,programacao,computador,computacao,codigo,software,dev,tecnologia,ti",
     "programacao,software,codigo,computacao,algoritmos,engenharia"),
    ("futuro,vigiar,vigiado,controle,ditadura,autoritarismo,censura",
     "distopia,vigilancia,totalitarismo,censura,controle"),
    ("guerra,batalha,combate,conflito,militar,estrategia,tatica",
     "guerra,batalha,estrategia,conflito"),
    ("politica,governo,governar,presidente,lideranca,lider",
     "politica,governo,poder,lideranca"),
    ("deus,religiao,religioso,espiritual,espiritualidade,biblia,cristao,igreja,fe",
     "fe,deus,espiritualidade,teologia,religiao"),
    ("filosofia,filosofico,pensar,pensamento,etica,moral,virtude,estoico",
     "filosofia,virtude,razao,etica,moral,estoicismo"),
    ("aventura,viagem,viajar,jornada,explorar", "aventura,jornada,viagem"),
    ("crianca,criancas,infantil,infancia,fabula", "infancia,fabula,infantil"),
    ("espaco,universo,estrelas,planetas,astronomia,fisica,ciencia,cientifico",
     "universo,astronomia,ciencia,fisica,cosmologia"),
    ("pobreza,pobre,desigualdade,miseria,fome,injustica,social",
     "pobreza,desigualdade,miseria,injustica,sociedade"),
    ("amor,romantico,paixao,namoro,casal,casamento", "amor,casamento,romance"),
    ("magia,magico,bruxo,bruxos,fantasia,dragao,dragoes", "magia,bruxos,dragao,fantasia"),
    ("humor,engracado,ironia,ironico,satira,comedia,rir", "satira,ironia,humor"),
    ("historia,historico,humanidade,civilizacao,evolucao", "humanidade,evolucao,imperios,civilizacao"),
    ("psicologia,mente,consciencia,culpa,crime", "psicologia,consciencia,culpa,crime"),
    ("vinganca,injusto,prisao,traicao", "vinganca,injustica,prisao,traicao"),
    ("solidao,sozinho,existencia,identidade", "solidao,existencia,identidade"),
    ("epico,epopeia,heroi,herois,mitologia,mito,deuses", "epico,herois,deuses,guerra"),
]

AFINIDADE_MINIMA = 0.10   # abaixo disso o livro não é considerado parecido


@dataclass
class Recomendacao:
    """Uma sugestão da IA: o livro, a afinidade (de 0 a 1), o selo que aparece no card e o motivo."""
    livro: dict
    afinidade: float        # 0..1, já calibrada para exibição
    selo: str
    motivo: str


def sem_acento(s: str) -> str:
    """Tira os acentos ("ação" vira "acao") para "ficção" e "ficcao" contarem como a mesma palavra."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def radical(t: str) -> str:
    """Tira o plural de um jeito simples: "livros" vira "livro" e "revoluções" vira "revolucao"."""
    if len(t) > 4 and t.endswith("oes"):
        return t[:-3] + "ao"
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def chave_autor(autor: str) -> str:
    """Junta o nome do autor num termo só ("George Orwell" vira "autor_george_orwell")."""
    return "autor_" + re.sub(r"[^a-z0-9]+", "_", sem_acento(autor.lower()))


def normalizar(v: dict) -> dict:
    """Divide o vetor pelo tamanho dele. Assim o cosseno vira só uma soma de multiplicações."""
    norma = math.sqrt(sum(x * x for x in v.values()))
    return {k: x / norma for k, x in v.items()} if norma else v


def cosseno(a: dict, b: dict) -> float:
    """Similaridade do cosseno entre dois vetores já normalizados: 0 = nada a ver, 1 = idênticos."""
    menor, maior = (a, b) if len(a) <= len(b) else (b, a)
    return sum(x * maior[k] for k, x in menor.items() if k in maior)


def calibrar(cos: float) -> float:
    """O cosseno costuma dar números baixos (tipo 0,35); aqui ele vira uma porcentagem mais fácil de entender."""
    return min(0.99, 1.0 - math.exp(-3.0 * cos))


class MotorIA:
    """O motor em si: aprende com o acervo quando é criado e depois responde as recomendações."""
    def __init__(self, livros: list):
        """Recebe os livros do banco e já treina o modelo na hora."""
        self.acervo = list(livros)
        self.exibicao = {}               # radical -> palavra original
        self.conceitos = {}              # radical da pergunta -> termos do acervo
        self.autores_por_palavra = {}    # 'orwell' -> {'autor_george_orwell'}
        self.idf = {}
        self.vetores = []
        self.maior_pop = max([l["popularidade"] for l in self.acervo] + [1])
        self._construir_conceitos()
        self._treinar()

    # ---- pré-processamento --------------------------------------------------
    def tokenizar(self, texto: str, registrar: bool = False) -> list:
        """Quebra o texto em palavras já limpas (minúsculas, sem acento, sem palavras vazias e sem plural)."""
        saida = []
        for bruto in re.split(r"[^\w]+|[\d_]+", (texto or "").lower()):
            if len(bruto) < 2:
                continue
            limpo = sem_acento(bruto)
            if limpo in STOPWORDS:
                continue
            r = radical(limpo)
            saida.append(r)
            if registrar and r not in self.exibicao:
                self.exibicao[r] = bruto
        return saida

    def _construir_conceitos(self):
        """Monta o "dicionário" que liga palavras da pergunta a termos do acervo (ex.: "programar" -> "software")."""
        for chaves, destino in CONCEITOS:
            termos = [radical(sem_acento(t.strip())) for t in destino.split(",")]
            for chave in chaves.split(","):
                k = radical(sem_acento(chave.strip()))
                self.conceitos.setdefault(k, [])
                for t in termos:
                    if t not in self.conceitos[k]:
                        self.conceitos[k].append(t)

    def _registrar_autor(self, autor: str):
        """Guarda as partes do nome do autor para a IA reconhecer quando alguém digitar só "Orwell", por exemplo."""
        for w in re.split(r"[^\w]+", autor.lower()):
            if len(w) < 4:
                continue
            r = radical(sem_acento(w))
            self.autores_por_palavra.setdefault(r, set()).add(chave_autor(autor))
            self.exibicao.setdefault(r, w)

    # ---- treino: TF-IDF -----------------------------------------------------
    def _treinar(self):
        """Calcula o IDF de cada termo e o vetor TF-IDF de cada livro. É o "aprendizado" do motor."""
        frequencias, docs_por_termo = [], {}
        for o in self.acervo:
            tf = {}
            for t in self.tokenizar(o["genero"], True):
                tf[t] = tf.get(t, 0) + 2.0
            ca = chave_autor(o["autor"])
            tf[ca] = tf.get(ca, 0) + 1.5
            self._registrar_autor(o["autor"])
            for t in self.tokenizar(o["palavras"], True):
                tf[t] = tf.get(t, 0) + 1.0
            frequencias.append(tf)
            for t in tf:
                docs_por_termo[t] = docs_por_termo.get(t, 0) + 1
        n = len(self.acervo)
        self.idf = {t: math.log((n + 1.0) / (d + 1.0)) + 1.0 for t, d in docs_por_termo.items()}
        self.vetores = [normalizar({t: f * self.idf[t] for t, f in tf.items()}) for tf in frequencias]

    def _termos_em_comum(self, a: dict, b: dict, i: int, maximo: int = 3) -> list:
        """Pega os termos que mais pesaram entre dois vetores. São eles que explicam a recomendação."""
        do_genero = set(self.tokenizar(self.acervo[i]["genero"]))
        pesos = {k: x * b[k] for k, x in a.items()
                 if k in b and k not in do_genero and not k.startswith("autor_")}
        ordem = sorted(pesos, key=pesos.get, reverse=True)[:maximo]
        return [self.exibicao.get(t, t) for t in ordem]

    # ---- recomendação 1: pelo histórico do leitor ---------------------------
    def recomendar_para_leitor(self, ids_lidos: list, maximo: int = 6) -> list:
        """Recomenda livros com base no que o leitor já leu.

        Livros já lidos ficam de fora e só entra quem passar da afinidade mínima.
        Se sobrar pouca coisa (ou o leitor ainda não leu nada), completa com os mais procurados.
        """
        lidos = [i for i, l in enumerate(self.acervo) if l["id"] in set(ids_lidos)]
        if not lidos:
            return self.mais_procuradas(maximo)
        perfil = {}
        for i in lidos:
            for k, x in self.vetores[i].items():
                perfil[k] = perfil.get(k, 0) + x
        perfil = normalizar(perfil)

        candidatos = [i for i in range(len(self.acervo)) if i not in lidos]
        score = {i: cosseno(perfil, self.vetores[i])
                 + 0.02 * self.acervo[i]["popularidade"] / self.maior_pop for i in candidatos}
        candidatos.sort(key=lambda i: score[i], reverse=True)

        saida, usados = [], set()
        for i in candidatos:
            if len(saida) >= maximo:
                break
            cos = cosseno(perfil, self.vetores[i])
            if cos < AFINIDADE_MINIMA:
                continue
            usados.add(i)
            af = calibrar(cos)
            saida.append(Recomendacao(self.acervo[i], af, f"{round(af * 100)}% de afinidade",
                                      self._explicar(i, lidos)))
        # se sobrou pouca coisa parecida, completa com os mais procurados
        for r in self.mais_procuradas(len(self.acervo)):
            if len(saida) >= maximo:
                break
            i = self.acervo.index(r.livro)
            if i in lidos or i in usados:
                continue
            r.motivo = "Não há mais obras muito parecidas com o histórico; esta é uma das mais procuradas."
            saida.append(r)
        return saida

    def _explicar(self, cand: int, lidos: list) -> str:
        """Monta a frase do porquê da indicação, ex.: "Porque leu 1984: temas em comum: distopia, censura"."""
        melhor = max(lidos, key=lambda i: cosseno(self.vetores[cand], self.vetores[i]))
        temas = self._termos_em_comum(self.vetores[cand], self.vetores[melhor], cand)
        lido = f"«{self.acervo[melhor]['titulo']}»"
        mesmo_autor = chave_autor(self.acervo[cand]["autor"]) == chave_autor(self.acervo[melhor]["autor"])
        autor = f"mesmo autor ({self.acervo[cand]['autor']})" if mesmo_autor else None
        tem = "temas em comum: " + ", ".join(temas) if temas else None
        if not autor and not tem:
            return f"Mesmo gênero de {lido} ({self.acervo[cand]['genero']})."
        if autor and tem:
            return f"Porque leu {lido}: {autor} e {tem}."
        return f"Porque leu {lido}: {autor or tem}."

    def mais_procuradas(self, maximo: int = 6) -> list:
        """Os livros mais emprestados. Servem para quem ainda não tem histórico."""
        ordem = sorted(self.acervo, key=lambda l: l["popularidade"], reverse=True)[:maximo]
        return [Recomendacao(l, 0, f"{l['popularidade']} empréstimos",
                             "Ainda não há histórico de leitura; a IA indica uma das obras mais procuradas.")
                for l in ordem]

    # ---- recomendação 2: por pergunta em linguagem natural ------------------
    def termos_reconhecidos(self, consulta: str) -> list:
        """As palavras da pergunta que a IA conseguiu ligar ao acervo (aparecem como "A IA entendeu: ...")."""
        saida = []
        for t in self.tokenizar(consulta):
            if t in self.idf or t in self.conceitos or t in self.autores_por_palavra:
                p = self.exibicao.get(t, t)
                if p not in saida:
                    saida.append(p)
        return saida

    def _vetor_consulta(self, consulta: str) -> dict:
        """Transforma a pergunta num vetor, somando também o autor citado e os conceitos relacionados."""
        q = {}
        for t in self.tokenizar(consulta):
            if t in self.idf:
                q[t] = q.get(t, 0) + self.idf[t]
            for a in self.autores_por_palavra.get(t, ()):
                q[a] = q.get(a, 0) + 1.5 * self.idf[a]
            for r in self.conceitos.get(t, ()):
                if r in self.idf:
                    q[r] = q.get(r, 0) + 0.6 * self.idf[r]
        return normalizar(q)

    def buscar_por_texto(self, consulta: str, maximo: int = 6) -> list:
        """Recomenda livros a partir de uma pergunta livre, tipo "quero algo de mistério"."""
        q = self._vetor_consulta(consulta)
        if not q:
            return []
        cos = [cosseno(q, v) for v in self.vetores]
        candidatos = sorted((i for i in range(len(self.acervo)) if cos[i] > 0.02),
                            key=lambda i: cos[i], reverse=True)[:maximo]
        resumo = consulta.strip()
        if len(resumo) > 40:
            resumo = resumo[:37] + "..."
        saida = []
        for i in candidatos:
            temas = self._termos_em_comum(self.vetores[i], q, i)
            livro = self.acervo[i]
            citou_autor = chave_autor(livro["autor"]) in q
            if citou_autor and not temas:
                motivo = f"Obra de {livro['autor']}, autor citado na busca."
            elif citou_autor:
                motivo = f"Obra de {livro['autor']} (citado na busca). Temas: {', '.join(temas)}."
            elif not temas:
                motivo = f"Combina com o pedido ({livro['genero']})."
            else:
                motivo = f"Combina com “{resumo}”. Temas encontrados: {', '.join(temas)}."
            af = calibrar(cos[i])
            saida.append(Recomendacao(livro, af, f"{round(af * 100)}% de afinidade", motivo))
        return saida
