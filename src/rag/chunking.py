"""Divisão das páginas extraídas em trechos (chunks) para indexação.

Fluxo de gerar_chunks:
    1. filtrar_paginas: descarta páginas curtas, de título, separadores de
       seção, páginas de navegação (referências, sumário...) e overlays do
       Beamer;
    2. preparar_texto: junta linhas quebradas e desfaz hifenização;
    3. agrupa páginas consecutivas do MESMO PDF em janelas;
    4. dividir_texto: divide chunks acima de MAX_TOKENS_CHUNK tokens.

Entrada: itens de src.rag.extracao, no formato
    {"texto": str, "arquivo": str, "pagina": int, "course_id": int}

Saída: um dict por chunk, com
    chunk_id    str  estável: "<course_id>:<arquivo>:<pagina>-<pagina_fim>",
                     com sufixo "#1", "#2"... só quando o chunk foi dividido
    texto       str
    arquivo     str
    pagina      int  primeira página do chunk
    pagina_fim  int  última página do chunk
    course_id   int
    caracteres  int  len(texto)
"""

import logging
import re
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache

logger = logging.getLogger(__name__)

MIN_CARACTERES = 50

# Separador de seção: página curta com todas as letras em maiúsculas
# ("HIPÓTESES", "MÉTODO CIENTÍFICO EM COMPUTAÇÃO").
MAX_CARACTERES_SEPARADOR = 120

# Limite de tokens por chunk, contando o prefixo "passage: " e os tokens
# especiais do tokenizador. O modelo trunca acima de 512.
MAX_TOKENS_CHUNK = 500
MODELO_TOKENIZADOR = "intfloat/multilingual-e5-base"
PREFIXO_PASSAGE = "passage: "

# Página de título: mais da metade das linhas se repete em 2+ PDFs do curso.
# Linhas com menos de MIN_PALAVRAS_LINHA_REPETIDA palavras são rótulos ou
# cabeçalhos ("Conteúdo", "Exercício 1") e não contam como repetidas.
MIN_PALAVRAS_LINHA_REPETIDA = 4

# Página de navegação: o título (1ª linha depois do cabeçalho de navegação,
# se houver) é um destes, comparado sem diferenciar maiúsculas nem acentos e
# aceitando numeração final ("Referências Bibliográficas I", "Sumário 2").
TITULOS_NAVEGACAO = {
    "referências",
    "referências bibliográficas",
    "próxima aula",
    "objetivos da aula",
    "conteúdo",
    "sumário",
    "agenda",
    "bibliografia",
    "bibliografia básica",
    "bibliografia complementar",
}

# Cabeçalho de navegação do Beamer (nomes das seções no topo do slide):
# linhas entre as MAX_LINHAS_CABECALHO primeiras da página que se repetem no
# topo de pelo menos FRACAO_CABECALHO das páginas do mesmo PDF (mínimo de
# MIN_PAGINAS_CABECALHO páginas).
MAX_LINHAS_CABECALHO = 6
FRACAO_CABECALHO = 0.5
MIN_PAGINAS_CABECALHO = 5

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


def _eh_separador(texto: str) -> bool:
    """Página curta com pelo menos uma letra e todas as letras maiúsculas."""
    if len(texto) >= MAX_CARACTERES_SEPARADOR:
        return False
    letras = [c for c in texto if c.isalpha()]
    return bool(letras) and all(c.isupper() for c in letras)


def _sem_acentos(texto: str) -> str:
    """Minúsculas, sem acentos e com espaços colapsados."""
    decomposto = unicodedata.normalize("NFKD", texto.casefold())
    return _normalizar("".join(c for c in decomposto if not unicodedata.combining(c)))


_TITULOS_NAVEGACAO = {_sem_acentos(t) for t in TITULOS_NAVEGACAO}
_NUMERACAO_FINAL = re.compile(r"\s+(?:\d{1,3}|[ivxlc]{1,6})$")


def _primeiras_linhas(texto: str) -> list[str]:
    return [l.strip() for l in texto.split("\n") if l.strip()][:MAX_LINHAS_CABECALHO]


def _cabecalhos_por_arquivo(paginas: list[dict]) -> dict[str, set[str]]:
    """Linhas normalizadas que formam o cabeçalho de navegação de cada PDF."""
    contagem: dict[str, Counter] = defaultdict(Counter)
    total: Counter = Counter()
    for p in paginas:
        total[p["arquivo"]] += 1
        contagem[p["arquivo"]].update({_normalizar(l) for l in _primeiras_linhas(p["texto"])})
    cabecalhos = {}
    for arquivo, linhas in contagem.items():
        minimo = max(MIN_PAGINAS_CABECALHO, FRACAO_CABECALHO * total[arquivo])
        cabecalhos[arquivo] = {l for l, n in linhas.items() if n >= minimo}
    return cabecalhos


def _titulo(texto: str, cabecalho: set[str]) -> str:
    """Primeira linha não vazia que não pertence ao cabeçalho de navegação."""
    linhas = [l.strip() for l in texto.split("\n") if l.strip()]
    for i, linha in enumerate(linhas):
        if i >= MAX_LINHAS_CABECALHO or _normalizar(linha) not in cabecalho:
            return linha
    return ""


def _eh_titulo_navegacao(titulo: str) -> bool:
    t = _sem_acentos(titulo).rstrip(":")
    return t in _TITULOS_NAVEGACAO or _NUMERACAO_FINAL.sub("", t) in _TITULOS_NAVEGACAO


def _marcar_overlays(paginas: list[dict]) -> dict[int, int]:
    """Encontra overlays do Beamer (\\pause, \\only...) entre páginas mantidas.

    Só compara páginas fisicamente consecutivas do mesmo PDF. Uma página é
    overlay quando seu texto normalizado é igual ao da seguinte ou está
    totalmente contido nele. Em cada sequência fica só a última página.

    Returns:
        {índice da página descartada em `paginas`: número da página mantida}.
    """
    normalizados = [_normalizar(p["texto"]) for p in paginas]
    overlay: dict[int, int] = {}
    for i in range(len(paginas) - 2, -1, -1):          # de trás para frente
        atual, seguinte = paginas[i], paginas[i + 1]
        if (atual["arquivo"] == seguinte["arquivo"]
                and seguinte["pagina"] == atual["pagina"] + 1
                and normalizados[i] in normalizados[i + 1]):
            overlay[i] = overlay.get(i + 1, seguinte["pagina"])
    return overlay


def filtrar_paginas(paginas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Separa as páginas mantidas das descartadas.

    Descarta, nesta ordem:
      - "curta": menos de MIN_CARACTERES caracteres;
      - "título": mais da metade das linhas normalizadas (minúsculas,
        espaços colapsados) aparece em 2 ou mais PDFs diferentes do curso.
        Linhas com menos de MIN_PALAVRAS_LINHA_REPETIDA palavras (rótulos e
        cabeçalhos) não contam como repetidas, então um cabeçalho repetido
        sozinho não descarta a página;
      - "separador": menos de MAX_CARACTERES_SEPARADOR caracteres e todas as
        letras em maiúsculas;
      - "navegacao": o título da página (1ª linha depois do cabeçalho de
        navegação do PDF, se houver; ver _cabecalhos_por_arquivo) está em
        TITULOS_NAVEGACAO, sem diferenciar maiúsculas nem acentos e
        aceitando numeração final ("Referências Bibliográficas I");
      - "overlay": entre as páginas que sobraram, página igual à seguinte do
        mesmo PDF ou contida nela (ver _marcar_overlays).

    Returns:
        (mantidas, descartadas). Cada descartada é
        {"arquivo": str, "pagina": int, "motivo": str, "detalhe": str};
        overlays têm também "mantida": int (página que ficou no lugar).
    """
    linhas_por_pagina = [_linhas_normalizadas(p["texto"]) for p in paginas]
    arquivos_por_linha: dict[str, set[str]] = defaultdict(set)
    for p, linhas in zip(paginas, linhas_por_pagina):
        for linha in linhas:
            arquivos_por_linha[linha].add(p["arquivo"])

    def repetida(linha: str) -> bool:
        return (len(linha.split()) >= MIN_PALAVRAS_LINHA_REPETIDA
                and len(arquivos_por_linha[linha]) >= 2)

    def descarte(p: dict, motivo: str, detalhe: str) -> dict:
        return {"arquivo": p["arquivo"], "pagina": p["pagina"], "motivo": motivo, "detalhe": detalhe}

    cabecalhos = _cabecalhos_por_arquivo(paginas)

    candidatas, descartadas = [], []
    for p, linhas in zip(paginas, linhas_por_pagina):
        repetidas = sum(1 for l in linhas if repetida(l))
        titulo = _titulo(p["texto"], cabecalhos[p["arquivo"]])
        if len(p["texto"]) < MIN_CARACTERES:
            descartadas.append(descarte(p, "curta", f"menos de {MIN_CARACTERES} caracteres"))
        elif linhas and repetidas > len(linhas) / 2:
            descartadas.append(descarte(
                p, "título", f"{repetidas}/{len(linhas)} linhas repetidas em 2+ PDFs"))
        elif _eh_separador(p["texto"]):
            descartadas.append(descarte(
                p, "separador",
                f"menos de {MAX_CARACTERES_SEPARADOR} caracteres, tudo em maiúsculas"))
        elif _eh_titulo_navegacao(titulo):
            descartadas.append(descarte(p, "navegacao", f"título: {titulo}"))
        else:
            candidatas.append(p)

    overlay = _marcar_overlays(candidatas)
    mantidas = []
    for i, p in enumerate(candidatas):
        if i in overlay:
            d = descarte(p, "overlay", f"contida na p.{overlay[i]}, que foi mantida")
            d["mantida"] = overlay[i]
            descartadas.append(d)
        else:
            mantidas.append(p)

    descartadas.sort(key=lambda d: (d["arquivo"], d["pagina"]))
    return mantidas, descartadas


@lru_cache(maxsize=1)
def _tokenizador():
    """Carrega o tokenizador do modelo de embeddings uma vez por processo."""
    from transformers import AutoTokenizer  # import tardio: só quem gera chunks paga

    return AutoTokenizer.from_pretrained(MODELO_TOKENIZADOR)


def contar_tokens(texto: str) -> int:
    """Tokens de "passage: <texto>", incluindo os tokens especiais."""
    # verbose=False: medir textos acima de 512 é intencional, sem aviso.
    ids = _tokenizador()(PREFIXO_PASSAGE + texto, add_special_tokens=True, verbose=False)["input_ids"]
    return len(ids)


# Níveis de quebra, do preferido ao último recurso: (regex de divisão, junção).
_NIVEIS_QUEBRA = [
    (re.compile(r"\n{2,}"), "\n\n"),                # parágrafo
    (re.compile(r"\n"), "\n"),                      # linha
    (re.compile(r"(?<=[.!?…;:])\s+"), " "),         # frase
    (re.compile(r"\s+"), " "),                      # palavra (meio da frase)
]


def _cortar_por_tokens(texto: str, max_tokens: int) -> list[str]:
    """Último recurso: corta em fronteiras de token (texto sem espaços)."""
    tok = _tokenizador()
    orcamento = max_tokens - contar_tokens("")
    offsets = tok(texto, add_special_tokens=False, return_offsets_mapping=True,
                  verbose=False)["offset_mapping"]
    partes = []
    for i in range(0, len(offsets), orcamento):
        bloco = offsets[i:i + orcamento]
        partes.append(texto[bloco[0][0]:bloco[-1][1]])
    return partes


def _dividir(texto: str, max_tokens: int, nivel: int) -> list[str]:
    if contar_tokens(texto) <= max_tokens:
        return [texto]
    if nivel >= len(_NIVEIS_QUEBRA):
        return _cortar_por_tokens(texto, max_tokens)

    regex, juncao = _NIVEIS_QUEBRA[nivel]
    pedacos = [p.strip() for p in regex.split(texto) if p.strip()]
    if len(pedacos) <= 1:
        return _dividir(texto, max_tokens, nivel + 1)

    partes, atual = [], ""
    for pedaco in pedacos:
        candidato = f"{atual}{juncao}{pedaco}" if atual else pedaco
        if contar_tokens(candidato) <= max_tokens:
            atual = candidato
            continue
        if atual:
            partes.append(atual)
        if contar_tokens(pedaco) <= max_tokens:
            atual = pedaco
        else:
            partes.extend(_dividir(pedaco, max_tokens, nivel + 1))
            atual = ""
    if atual:
        partes.append(atual)
    return partes


def dividir_texto(texto: str, max_tokens: int = MAX_TOKENS_CHUNK) -> list[str]:
    """Divide `texto` em partes de até `max_tokens` tokens (ver contar_tokens).

    Agrupa o máximo possível por parte, preferindo quebrar entre parágrafos,
    depois entre linhas, depois entre frases. Só corta no meio de uma frase
    (entre palavras, ou entre tokens) quando não há outra opção.
    Texto que já cabe volta inteiro, numa lista de um item.
    """
    return _dividir(texto, max_tokens, 0)


def gerar_chunks(paginas: list[dict], janela: int = 1, sobreposicao: int = 0,
                 max_tokens: int = MAX_TOKENS_CHUNK) -> list[dict]:
    """Gera chunks agrupando `janela` páginas consecutivas de cada PDF.

    A janela avança `janela - sobreposicao` páginas por vez e conta apenas
    as páginas mantidas pelo filtro. Páginas de PDFs diferentes nunca são
    juntadas. A última janela de cada PDF pode ser menor que `janela`.

    Um chunk com mais de `max_tokens` tokens é dividido (dividir_texto). As
    partes mantêm arquivo, pagina, pagina_fim e course_id do chunk original
    e recebem o sufixo "#1", "#2"... no chunk_id.

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
            base_id = f"{course_id}:{arquivo}:{primeira}-{ultima}"
            partes = dividir_texto(texto, max_tokens)
            for n, parte in enumerate(partes, start=1):
                chunks.append({
                    "chunk_id": base_id if len(partes) == 1 else f"{base_id}#{n}",
                    "texto": parte,
                    "arquivo": arquivo,
                    "pagina": primeira,
                    "pagina_fim": ultima,
                    "course_id": course_id,
                    "caracteres": len(parte),
                })
            if inicio + janela >= len(pags):
                break
    return chunks
