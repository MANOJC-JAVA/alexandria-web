# Alexandria Web — Sistema de Gestão de Biblioteca

Projeto Integrador: Programação WEB — CST em Análise e Desenvolvimento de Sistemas / Gestão de TI — UNISA.

Versão web do Alexandria, que antes era um aplicativo desktop em Java Swing. O sistema controla o acervo,
os empréstimos, as devoluções, as renovações e as reservas de uma biblioteca acadêmica. Ele também tem um
**motor de recomendação com Inteligência Artificial** (TF-IDF e similaridade do cosseno) que sugere livros
para cada leitor e responde perguntas em linguagem natural.

## Tecnologias

| Camada | Tecnologia |
| :-- | :-- |
| Servidor (back-end) | Python 3.10+ com Flask 3 (rotas, sessões, templates Jinja2) |
| Banco de dados | SQLite 3 (arquivo `instance/alexandria.db`, criado automaticamente) |
| Interface (front-end) | HTML5, CSS3 (layout responsivo com Grid e Flexbox) e JavaScript puro |
| Inteligência Artificial | `ia.py`: TF-IDF + similaridade do cosseno, sem bibliotecas externas |
| Segurança | Senhas com hash PBKDF2 (Werkzeug), token CSRF nos formulários, consultas SQL parametrizadas, controle de acesso por perfil |
| Testes | `unittest` (29 testes automatizados) |

## Como rodar

Pré-requisito: **Python 3.10 ou superior** (<https://www.python.org/downloads/>; no Windows, marque *Add Python to PATH*).

**Windows:** dê dois cliques em `rodar.bat`.
**Linux/Mac:** `./rodar.sh`

Ou manualmente, na pasta do projeto:

```bash
pip install -r requirements.txt
python app.py
```

Depois, abra **http://127.0.0.1:5000** no navegador. Na primeira execução, o banco é criado com os dados de exemplo
convertidos da versão desktop (40 livros, 10 usuários, empréstimos e reservas).

Para voltar aos dados de exemplo, pare o servidor e apague a pasta `instance/`.

### Logins de teste

| Perfil | E-mail | Senha |
| :-- | :-- | :-- |
| Administrador | `augusto.bento@alexandria.com.br` | `Adm1958` |
| Bibliotecária | `karine.varela@alexandria.com.br` | `Adm2608` |
| Leitor (estudante) | `ana.silva@aluno.edu.br` | `2023001` (matrícula) |

O leitor vê um menu reduzido: Início (com as recomendações dele), Pesquisar livros e as próprias Reservas.

### Rodar os testes

```bash
python -m unittest discover -s testes -v
```

## Funcionalidades (casos de uso)

| Caso de uso | Rota | Perfil |
| :-- | :-- | :-- |
| UC01 Autenticar-se / UC16 Sair | `/login`, `/sair` | todos |
| UC02 Painel inicial com indicadores | `/inicio` | equipe |
| UC03 Consultar catálogo (busca, filtros, ordenação, grade/lista, 8 por página) | `/catalogo` | todos |
| UC04 Ver detalhes do livro | `/livro/<id>` | todos |
| UC05 Cadastrar livro (com pré-visualização da capa) | `/acervo` | equipe |
| UC06 Registrar empréstimo | `/emprestimos` | equipe |
| UC07 Registrar devolução / UC08 Renovar | `/emprestimos/<id>/devolver`, `/renovar` | equipe |
| UC09 Reservar / UC10 Cancelar reserva | `/reservas` | todos (leitor só as próprias) |
| UC11 Gerenciar usuários / UC12 Exportar CSV | `/usuarios`, `/usuarios.csv` | equipe |
| UC13 Recomendações da IA por leitor / UC14 por pergunta | `/inicio?leitor=`, `/inicio?pergunta=` | todos |
| UC15 Relatórios | `/relatorios` | equipe |
| UC17 Acesso do leitor | `/login` (e-mail + matrícula) | leitor |

### Regras de negócio

- Estudante: até **3** empréstimos simultâneos, prazo de **14 dias**. Demais tipos: até **5**, prazo de **21 dias**.
- O livro precisa ter exemplar disponível. O leitor precisa estar ativo e não pode ter devolução em atraso.
- No máximo **2 renovações** por empréstimo. A renovação é bloqueada se houver reserva aguardando o livro.
- Reserva só para livro sem exemplar livre. Estados: `AGUARDANDO` → `PRONTA` (quando o livro volta; o exemplar fica separado para quem reservou) → `ATENDIDA` (quando é retirado) ou `CANCELADA`. Se uma reserva pronta é cancelada, o exemplar passa ao próximo da fila.
- Um usuário com empréstimo ativo não pode ser removido.

## Estrutura do código

```
app.py              rotas Flask (controladores), sessão, controle de acesso e CSRF
regras.py           regras de negócio e consultas SQL (empréstimo, devolução, reserva...)
ia.py               motor de recomendação (TF-IDF + cosseno)
banco.py            conexão com o SQLite e criação do banco
schema.sql          modelo físico do banco (tabelas, chaves e restrições)
dados_exemplo.sql   carga inicial (convertida do dados.txt da versão desktop)
templates/          páginas HTML (Jinja2)
static/css, js/     estilo e comportamento da interface
testes/             testes automatizados
ferramentas/        conversor dados.txt → SQL
```

## Modelo de dados

```
funcionarios (id, email, senha_hash, nome, cargo, ativo)
pessoas      (id, nome, email, telefone, tipo, matricula, ativo, desde)
livros       (id, titulo, autor, genero, ano, isbn, local, sinopse, palavras, total, disponiveis, tom, especial, popularidade)
emprestimos  (id, livro_id → livros, pessoa_id → pessoas, retirada, previsto, devolvido, renovacoes)
reservas     (id, livro_id → livros, pessoa_id → pessoas, data, estado)
```
