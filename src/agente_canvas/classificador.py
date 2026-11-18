# src/agente_canvas/classificador.py
"""Classificador por regras (sem LLM) dos arquivos de um curso no Canvas.

A função `classificar` recebe metadados já conhecidos do arquivo (nome, módulo,
pasta, tamanho em bytes e nº de páginas) e devolve `(categoria, origem)`:

  categoria: "slides" | "listas" | "trabalho" | "livros" | "indefinido"
  origem:    o nome da regra que decidiu (ex.: "nome:lista", "modulo:aula",
             "paginas>100").

As camadas são avaliadas em ordem; a primeira que decide encerra. Todos os
textos são normalizados (minúsculas, sem acentos) antes de comparar.
"""

import re
import unicodedata

# Palavras de cada camada (já sem acento, pois comparamos contra texto normalizado).
PALAVRAS_LISTAS = ["lista", "exercicio", "ex_", "atividade"]
PALAVRAS_TRABALHO = ["roteiro", "template", "modelo", "aps", "trabalho final"]
PALAVRAS_LIVROS = ["livro", "pmbok", "guia"]
PALAVRAS_AULA = ["aula", "slide"]

# Camada do módulo: as mesmas palavras de (a) e (b), mais "aula" e "slide".
PALAVRAS_MODULO = (
    PALAVRAS_LISTAS + PALAVRAS_TRABALHO + PALAVRAS_LIVROS + PALAVRAS_AULA
)

# Padrão de edição: "7ed", "7a ed", "7 ed", "edicao".
RE_EDICAO = re.compile(r"\d+\s*a?\s*ed|edicao")
# Nome que começa com "A" + número + " -" (ex.: "A2 - ...").
RE_AULA_PREFIXO = re.compile(r"^a\d+\s*-")

# Limiares da camada (e).
MAX_PAGINAS = 100
MAX_TAMANHO_BYTES = 20 * 1024 * 1024  # 20 MB


def normalizar(texto) -> str:
    """Minúsculas e sem acentos; `None`/vazio viram string vazia."""
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()


def _primeira_palavra(texto: str, palavras) -> str | None:
    """Primeira palavra da lista que aparece como substring de `texto`."""
    for p in palavras:
        if p in texto:
            return p
    return None


def classificar(nome, modulo=None, pasta=None, tamanho=None, paginas=None):
    """Classifica um arquivo por regras. Ver docstring do módulo."""
    n = normalizar(nome)
    m = normalizar(modulo)

    # (a) nome do arquivo: listas / trabalho
    p = _primeira_palavra(n, PALAVRAS_LISTAS)
    if p:
        return "listas", f"nome:{p}"
    p = _primeira_palavra(n, PALAVRAS_TRABALHO)
    if p:
        return "trabalho", f"nome:{p}"

    # (b) nome do arquivo: livros
    p = _primeira_palavra(n, PALAVRAS_LIVROS)
    if p:
        return "livros", f"nome:{p}"
    if RE_EDICAO.search(n):
        return "livros", "nome:edicao"

    # (c) nome do módulo: mesmas palavras de (a) e (b) + aula/slide -> slides
    if m:
        p = _primeira_palavra(m, PALAVRAS_MODULO)
        if p:
            return "slides", f"modulo:{p}"
        if RE_EDICAO.search(m):
            return "slides", "modulo:edicao"

    # (d) nome do arquivo: aula/slide ou prefixo "A<num> -"
    p = _primeira_palavra(n, PALAVRAS_AULA)
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
