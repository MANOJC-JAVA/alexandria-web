"""
Converte o arquivo dados.txt da versão desktop (Java Swing) do Alexandria
para comandos SQL de carga inicial (dados_exemplo.sql) da versão web.

Uso:  python ferramentas/converter_dados_txt.py caminho/dados.txt > dados_exemplo.sql

Formato do dados.txt (campos separados por TAB):
  L = livro, P = pessoa, E = empréstimo, R = reserva  (C = contadores, ignorado)
"""
import sys


def desescapar(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            i += 1
            n = s[i]
            out.append("\t" if n == "t" else "\n" if n == "n" else n)
        else:
            out.append(c)
        i += 1
    return "".join(out)


def q(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def main(caminho: str) -> None:
    livros, pessoas, emps, res = [], [], [], []
    with open(caminho, encoding="utf-8") as arq:
        for bruta in arq:
            bruta = bruta.rstrip("\n")
            if not bruta or bruta.startswith("#") or bruta.startswith("ALEXANDRIA"):
                continue
            f = [desescapar(x) for x in bruta.split("\t")]
            if f[0] == "L":
                livros.append((int(f[1]), f[2], f[3], f[4], int(f[5]), f[6], f[7], f[8], f[9],
                               int(f[10]), int(f[11]), f[12], 1 if f[13] == "true" else 0, int(f[14])))
            elif f[0] == "P":
                pessoas.append((int(f[1]), f[2], f[3], f[4], f[5], f[6], 1 if f[7] == "true" else 0, f[8]))
            elif f[0] == "E":
                emps.append((int(f[1]), int(f[2]), int(f[3]), f[4], f[5], None if f[6] == "-" else f[6], int(f[7])))
            elif f[0] == "R":
                res.append((int(f[1]), int(f[2]), int(f[3]), f[4], f[5]))

    print("-- Dados de exemplo convertidos do dados.txt da versão desktop")
    cols = {
        "livros": "id, titulo, autor, genero, ano, isbn, local, sinopse, palavras, total, disponiveis, tom, especial, popularidade",
        "pessoas": "id, nome, email, telefone, tipo, matricula, ativo, desde",
        "emprestimos": "id, livro_id, pessoa_id, retirada, previsto, devolvido, renovacoes",
        "reservas": "id, livro_id, pessoa_id, data, estado",
    }
    for tabela, linhas in (("livros", livros), ("pessoas", pessoas), ("emprestimos", emps), ("reservas", res)):
        for linha in linhas:
            print(f"INSERT INTO {tabela} ({cols[tabela]}) VALUES ({', '.join(q(v) for v in linha)});")


if __name__ == "__main__":
    main(sys.argv[1])
