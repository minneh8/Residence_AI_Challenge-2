# src/agente_canvas/classificador.py
"""Classificador por regras (sem LLM) dos arquivos de um curso no Canvas.

A função `classificar` recebe metadados já conhecidos do arquivo (nome, módulo,
pasta, tamanho em bytes e nº de páginas) e devolve `(categoria, origem)`:

  categoria: "slides" | "listas" | "trabalho" | "livros" | "indefinido"
  origem:    o nome da regra que decidiu (ex.: "nome:lista", "modulo:aula",
             "paginas>100").

As camadas são avaliadas em ordem; a primeira que decide encerra. Todos os
textos são normalizados (minúsculas, sem acentos) e divididos em palavras
inteiras antes de comparar, para que "aps" não case com "etapas" nem "mapas".
"""

import re
import unicodedata

# Palavras do nome do arquivo (já sem acento, pois comparamos contra texto
# normalizado). Cada palavra casa também com o plural em "s".
PALAVRAS_LISTAS = ["lista", "exercicio", "atividade"]
PREFIXO_LISTAS = "ex_"  # prefixo do nome, não palavra inteira
PALAVRAS_TRABALHO = ["roteiro", "template", "modelo", "aps", "trabalho final"]
PALAVRAS_LIVROS = ["livro", "pmbok", "guia"]
PALAVRAS_AULA = ["aula", "slide"]

# Camada do módulo: cada conjunto decide a sua categoria. Módulo sem nenhuma
# dessas palavras (ex.: "Qualidade", "Custos") não decide.
PALAVRAS_MODULO = [
    ("listas", ["lista", "exercicio", "atividade", "entrega"]),
    ("trabalho", ["roteiro", "trabalho", "projeto"]),
    ("livros", ["livro", "bibliografia", "leitura"]),
    ("slides", ["aula", "slide"]),
]

# Padrão de edição: "7ed", "7a ed", "7 ed", "edicao".
RE_EDICAO = re.compile(r"\d+\s*a?\s*ed|edicao")
# Nome que começa com "A" + número + " -" (ex.: "A2 - ...").
RE_AULA_PREFIXO = re.compile(r"^a\d+\s*-")
# Fronteira camelCase ("RoteiroTrabalhoFinal" -> "Roteiro Trabalho Final").
RE_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")

# Limiares da camada (e).
MAX_PAGINAS = 100
MAX_TAMANHO_BYTES = 20 * 1024 * 1024  # 20 MB


def normalizar(texto) -> str:
    """Minúsculas e sem acentos; `None`/vazio viram string vazia."""
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()


def tokens(texto) -> str:
    """Palavras inteiras do texto, separadas por um espaço e com espaço nas pontas.

    Divide em camelCase, em qualquer caractere não alfanumérico e na fronteira
    entre letras e dígitos ("aula03" -> "aula 03").
    """
    texto = normalizar(RE_CAMEL.sub(" ", texto or ""))
    return " " + " ".join(re.findall(r"[a-z]+|\d+", texto)) + " "


def _primeira_palavra(toks: str, palavras) -> str | None:
    """Primeira palavra (ou expressão) da lista presente inteira em `toks`.

    Aceita também o plural simples em "s" ("slides" casa com "slide").
    """
    for p in palavras:
        if f" {p} " in toks or f" {p}s " in toks:
            return p
    return None


def classificar(nome, modulo=None, pasta=None, tamanho=None, paginas=None):
    """Classifica um arquivo por regras. Ver docstring do módulo."""
    n = normalizar(nome)
    tn = tokens(nome)
    tm = tokens(modulo)

    # (a) nome do arquivo: listas / trabalho
    if n.startswith(PREFIXO_LISTAS):
        return "listas", f"nome:{PREFIXO_LISTAS}"
    p = _primeira_palavra(tn, PALAVRAS_LISTAS)
    if p:
        return "listas", f"nome:{p}"
    p = _primeira_palavra(tn, PALAVRAS_TRABALHO)
    if p:
        return "trabalho", f"nome:{p}"

    # (b) nome do arquivo: livros
    p = _primeira_palavra(tn, PALAVRAS_LIVROS)
    if p:
        return "livros", f"nome:{p}"
    if RE_EDICAO.search(n):
        return "livros", "nome:edicao"

    # (c) nome do módulo: cada conjunto decide a sua categoria; módulo neutro
    # passa para a próxima camada
    for categoria, palavras in PALAVRAS_MODULO:
        p = _primeira_palavra(tm, palavras)
        if p:
            return categoria, f"modulo:{p}"

    # (d) nome do arquivo: aula/slide ou prefixo "A<num> -"
    p = _primeira_palavra(tn, PALAVRAS_AULA)
    if p:
        return "slides", f"nome:{p}"
    if RE_AULA_PREFIXO.search(n):
        return "slides", "nome:A<num>-"

    # (e) páginas > 100 ou tamanho > 20 MB -> livros
    if paginas is not None and paginas > MAX_PAGINAS:
        return "livros", "paginas>100"
    if tamanho is not None and tamanho > MAX_TAMANHO_BYTES:
        return "livros", "tamanho>20MB"

    # (f) nada decidiu
    return "indefinido", "nenhuma"
