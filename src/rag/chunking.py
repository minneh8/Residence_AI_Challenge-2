"""Divisão das páginas extraídas em trechos (chunks) para indexação.

Fluxo de gerar_chunks:
    1. filtrar_paginas: descarta páginas curtas e páginas de título;
    2. preparar_texto: junta linhas quebradas e desfaz hifenização;
    3. agrupa páginas consecutivas do MESMO PDF em janelas.

Entrada: itens de src.rag.extracao, no formato
    {"texto": str, "arquivo": str, "pagina": int, "course_id": int}

Saída: um dict por chunk, com
    chunk_id    str  estável: "<course_id>:<arquivo>:<pagina>-<pagina_fim>"
    texto       str
    arquivo     str
    pagina      int  primeira página do chunk
    pagina_fim  int  última página do chunk
    course_id   int
    caracteres  int  len(texto)
"""

import logging
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

MIN_CARACTERES = 50

# Página de título: mais da metade das linhas se repete em 2+ PDFs do curso.
# Linhas com menos de MIN_PALAVRAS_LINHA_REPETIDA palavras são rótulos ou
# cabeçalhos ("Conteúdo", "Exercício 1") e não contam como repetidas.
MIN_PALAVRAS_LINHA_REPETIDA = 4

# Compostos reais que não devem perder o hífen ao juntar linhas.
# Comparação sem diferenciar maiúsculas; a grafia original é preservada.
EXCECOES_HIFENIZACAO = {
    "hipotético-dedutivo",
}
_EXCECOES_HIFEN = {e.casefold() for e in EXCECOES_HIFENIZACAO}

# Itens de lista: marcadores gráficos ou enumerações "1.", "a)", "iv." etc.
_ITEM_LISTA = re.compile(r"^(?:[•▪▸►▶○●■□☐✓✔→\-–—*]|(?:\d{1,3}|[a-zA-Z]|[ivxIVX]{1,5})[.)]\s)")
_OPERADORES = re.compile(r"[=<>≤≥≠≈±×÷∑√^]")
_CHAMADA_METODO = re.compile(r"[\w\])]\.\w+\(")   # plt.savefig(, df.mean(
_CHAMADA = re.compile(r"\w\(")                     # print(, f(
_HIFEN_FINAL = re.compile(r"[^\W\d_]-$")           # letra + hífen no fim
_ULTIMA_PALAVRA_HIFEN = re.compile(r"(\w+)-$")
_PRIMEIRA_PALAVRA = re.compile(r"\w+")
_CONECTIVOS = {
    "e", "ou", "de", "da", "do", "das", "dos", "em", "na", "no", "nas", "nos",
    "a", "o", "as", "os", "com", "para", "por", "pela", "pelo", "que", "um", "uma",
    "and", "or", "of", "the", "in", "on", "for", "to", "with",
}


def _eh_formula_ou_codigo(linha: str) -> bool:
    """Heurística: linha curta com operadores ou com cara de código."""
    if _CHAMADA_METODO.search(linha):
        return True
    operadores = len(_OPERADORES.findall(linha))
    if operadores >= 2:
        return True
    if (operadores or _CHAMADA.search(linha)) and len(linha.split()) <= 6:
        return True
    return bool(_OPERADORES.search(linha[-1:]))  # termina em operador: "g1 ="


def _deve_juntar(anterior: str, proxima: str) -> bool:
    """Decide se `proxima` continua a frase de `anterior`."""
    if not anterior or not proxima:
        return False                       # linha vazia = quebra de parágrafo
    if _ITEM_LISTA.match(proxima):
        return False
    if _eh_formula_ou_codigo(anterior) or _eh_formula_ou_codigo(proxima):
        return False
    if proxima[0].islower():
        return True
    if anterior.endswith(","):
        return True
    ultima_palavra = anterior.rsplit(" ", 1)[-1].lower()
    return ultima_palavra in _CONECTIVOS


def _eh_composto_excecao(anterior: str, proxima: str) -> bool:
    """True se "<fim de anterior>-<início de proxima>" está nas exceções."""
    antes = _ULTIMA_PALAVRA_HIFEN.search(anterior)
    depois = _PRIMEIRA_PALAVRA.match(proxima)
    if not antes or not depois:
        return False
    return f"{antes.group(1)}-{depois.group(0)}".casefold() in _EXCECOES_HIFEN


def preparar_texto(texto: str) -> str:
    """Junta linhas quebradas e desfaz hifenização no fim da linha.

    Preserva quebras antes de itens de lista, ao redor de fórmulas/código
    e entre parágrafos (linha vazia). Hifenização só é desfeita quando a
    linha seguinte começa com minúscula ("experi-" + "mento"). Compostos
    listados em EXCECOES_HIFENIZACAO mantêm o hífen ("Hipotético-dedutivo").
    """
    linhas = texto.split("\n")
    saida: list[str] = []
    for linha in linhas:
        if saida and _eh_composto_excecao(saida[-1], linha):
            saida[-1] = saida[-1] + linha                 # mantém o hífen
        elif saida and _deve_juntar(saida[-1], linha):
            anterior = saida[-1]
            if _HIFEN_FINAL.search(anterior) and linha[0].islower():
                saida[-1] = anterior[:-1] + linha
            else:
                saida[-1] = anterior + " " + linha
        else:
            saida.append(linha)
    return "\n".join(saida)


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip().lower()


def _linhas_normalizadas(texto: str) -> list[str]:
    """Linhas não vazias, após juntar quebras, normalizadas para comparação."""
    return [n for n in (_normalizar(l) for l in preparar_texto(texto).split("\n")) if n]


def filtrar_paginas(paginas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Separa as páginas mantidas das descartadas.

    Descarta:
      - páginas com menos de MIN_CARACTERES caracteres;
      - páginas de título: mais da metade das linhas normalizadas (minúsculas,
        espaços colapsados) aparece em 2 ou mais PDFs diferentes do curso.
        Linhas com menos de MIN_PALAVRAS_LINHA_REPETIDA palavras (rótulos e
        cabeçalhos) não contam como repetidas, então um cabeçalho repetido
        sozinho não descarta a página.

    Returns:
        (mantidas, descartadas). Cada descartada é
        {"arquivo": str, "pagina": int, "motivo": str}.
    """
    linhas_por_pagina = [_linhas_normalizadas(p["texto"]) for p in paginas]
    arquivos_por_linha: dict[str, set[str]] = defaultdict(set)
    for p, linhas in zip(paginas, linhas_por_pagina):
        for linha in linhas:
            arquivos_por_linha[linha].add(p["arquivo"])

    def repetida(linha: str) -> bool:
        return (len(linha.split()) >= MIN_PALAVRAS_LINHA_REPETIDA
                and len(arquivos_por_linha[linha]) >= 2)

    mantidas, descartadas = [], []
    for p, linhas in zip(paginas, linhas_por_pagina):
        repetidas = sum(1 for l in linhas if repetida(l))
        if len(p["texto"]) < MIN_CARACTERES:
            motivo = f"menos de {MIN_CARACTERES} caracteres"
        elif linhas and repetidas > len(linhas) / 2:
            motivo = f"página de título ({repetidas}/{len(linhas)} linhas repetidas em 2+ PDFs)"
        else:
            mantidas.append(p)
            continue
        descartadas.append({"arquivo": p["arquivo"], "pagina": p["pagina"], "motivo": motivo})
    return mantidas, descartadas


def gerar_chunks(paginas: list[dict], janela: int = 1, sobreposicao: int = 0) -> list[dict]:
    """Gera chunks agrupando `janela` páginas consecutivas de cada PDF.

    A janela avança `janela - sobreposicao` páginas por vez e conta apenas
    as páginas mantidas pelo filtro. Páginas de PDFs diferentes nunca são
    juntadas. A última janela de cada PDF pode ser menor que `janela`.

    Raises:
        ValueError: se janela < 1 ou se sobreposicao não estiver em [0, janela).
    """
    if not isinstance(janela, int) or janela < 1:
        raise ValueError("janela deve ser um inteiro >= 1.")
    if not isinstance(sobreposicao, int) or not 0 <= sobreposicao < janela:
        raise ValueError("sobreposicao deve ser um inteiro com 0 <= sobreposicao < janela.")

    mantidas, descartadas = filtrar_paginas(paginas)
    if descartadas:
        logger.info(
            "%d página(s) descartada(s): %s",
            len(descartadas),
            ", ".join(f"{d['arquivo']} p.{d['pagina']}" for d in descartadas),
        )

    por_arquivo: dict[str, list[dict]] = {}
    for p in mantidas:
        por_arquivo.setdefault(p["arquivo"], []).append(p)

    passo = janela - sobreposicao
    chunks = []
    for arquivo, pags in por_arquivo.items():
        pags = sorted(pags, key=lambda p: p["pagina"])
        for inicio in range(0, len(pags), passo):
            grupo = pags[inicio:inicio + janela]
            texto = "\n\n".join(preparar_texto(p["texto"]) for p in grupo)
            primeira, ultima = grupo[0]["pagina"], grupo[-1]["pagina"]
            course_id = grupo[0]["course_id"]
            chunks.append({
                "chunk_id": f"{course_id}:{arquivo}:{primeira}-{ultima}",
                "texto": texto,
                "arquivo": arquivo,
                "pagina": primeira,
                "pagina_fim": ultima,
                "course_id": course_id,
                "caracteres": len(texto),
            })
            if inicio + janela >= len(pags):
                break
    return chunks
