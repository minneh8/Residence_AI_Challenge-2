"""Extração de texto dos PDFs das disciplinas.

Os PDFs ficam em data/raw/<course_id>/. A extração gera um item por página,
preservando arquivo e número da página para que a busca possa citar a fonte.

Formato de cada item:
    {"texto": str, "arquivo": str, "pagina": int, "course_id": int}

    arquivo  nome do PDF (sem diretório), ex.: "aula01.pdf"
    pagina   posição física da página no PDF, começando em 1

Não há OCR: páginas escaneadas ou só com imagens saem com pouco ou nenhum
texto. O script scripts/testar_extracao.py sinaliza essas páginas.

Páginas curtas ou vazias são mantidas aqui; o descarte é feito no chunking.
"""

import logging
import re
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)

# Raiz do repositório (src/rag/extracao.py -> parents[2]).
RAIZ_REPO = Path(__file__).resolve().parents[2]
DIR_RAW = RAIZ_REPO / "data" / "raw"

# Espaços "exóticos" que viram espaço comum (NBSP, espaços finos, etc.).
_ESPACOS_UNICODE = re.compile(r"[  -   　]")
_ESPACOS_REPETIDOS = re.compile(r"[ \t\f\v]+")
_QUEBRAS_EXCESSIVAS = re.compile(r"\n{3,}")

# "≠" vindo do LaTeX como U+0338 (barra combinante) seguido de "=".
# Ex.: "µA̸ = µB" -> "µA ≠ µB". U+0338 isolado não é alterado.
_DIFERENTE_QUEBRADO = re.compile(r"[ \t]*̸[ \t]*=")

# Caixa de checklist "□" vira marcador de lista "- ", um item por linha.
_CHECKLIST_INICIO = re.compile(r"(?m)^[ \t]*□[ \t]*")
_CHECKLIST_MEIO = re.compile(r"[ \t]*□[ \t]*")

# Numeração de slide do Beamer ("19 / 33") numa linha própria no fim da página.
_RODAPE_NUMERACAO = re.compile(r"(?:^|\n)(\d{1,4}) ?/ ?(\d{1,4})$")


def limpar_texto(texto: str) -> str:
    """Limpeza leve: normaliza espaços e quebras de linha, sem remover conteúdo.

    - padroniza quebras de linha (\\r\\n e \\r -> \\n);
    - corrige "≠" extraído como U+0338 seguido de "=";
    - troca a caixa de checklist "□" por "- ", com cada item em sua linha;
    - troca espaços Unicode especiais por espaço comum;
    - reduz sequências de espaços/tabs a um espaço;
    - remove espaços no início e no fim de cada linha;
    - reduz 3 ou mais quebras de linha seguidas a 2 (mantém parágrafos);
    - remove espaços e quebras no início e no fim da página.
    """
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = _DIFERENTE_QUEBRADO.sub(" ≠", texto)
    texto = _CHECKLIST_INICIO.sub("- ", texto)
    texto = _CHECKLIST_MEIO.sub("\n- ", texto)
    texto = _ESPACOS_UNICODE.sub(" ", texto)
    texto = _ESPACOS_REPETIDOS.sub(" ", texto)
    texto = "\n".join(linha.strip() for linha in texto.split("\n"))
    texto = _QUEBRAS_EXCESSIVAS.sub("\n\n", texto)
    return texto.strip()


def remover_rodape_numeracao(texto: str) -> str:
    """Remove o rodapé "N / M" apenas se for a última linha, sozinho.

    Só remove quando N <= M, para não apagar uma fração solta como "3 / 2".
    Espera texto já passado por limpar_texto.
    """
    m = _RODAPE_NUMERACAO.search(texto)
    if m and int(m.group(1)) <= int(m.group(2)):
        return texto[: m.start()].rstrip()
    return texto


def listar_pdfs(course_id: int) -> list[Path]:
    """Lista, em ordem alfabética, os PDFs de data/raw/<course_id>/.

    Raises:
        FileNotFoundError: se a pasta do curso não existir.
    """
    pasta = DIR_RAW / str(course_id)
    if not pasta.is_dir():
        raise FileNotFoundError(f"Pasta do curso não encontrada: {pasta}")
    return sorted(
        (p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
        key=lambda p: p.name.lower(),
    )


def extrair_pdf(caminho: Path, course_id: int) -> list[dict]:
    """Extrai o texto de um PDF, com um item por página.

    Páginas sem texto também são retornadas (com texto vazio), para que a
    numeração fique completa e seja possível identificar onde falta OCR.

    Raises:
        FileNotFoundError: se o arquivo não existir.
        ValueError: se o PDF estiver protegido por senha.
        pymupdf.FileDataError: se o arquivo estiver corrompido ou não for PDF.
    """
    caminho = Path(caminho)
    if not caminho.is_file():
        raise FileNotFoundError(f"PDF não encontrado: {caminho}")

    itens = []
    with pymupdf.open(caminho) as doc:
        if doc.needs_pass:
            raise ValueError(f"PDF protegido por senha: {caminho.name}")
        for numero, pagina in enumerate(doc, start=1):
            itens.append({
                "texto": remover_rodape_numeracao(limpar_texto(pagina.get_text("text"))),
                "arquivo": caminho.name,
                "pagina": numero,
                "course_id": course_id,
            })
    return itens


def extrair_curso(course_id: int) -> list[dict]:
    """Extrai todos os PDFs de data/raw/<course_id>/.

    Se um PDF falhar, o erro é registrado no log e os demais continuam.
    Retorna os itens de todos os PDFs, na ordem de listar_pdfs.

    Raises:
        FileNotFoundError: se a pasta do curso não existir.
    """
    pdfs = listar_pdfs(course_id)
    if not pdfs:
        logger.warning("Nenhum PDF encontrado para o curso %s.", course_id)

    itens = []
    for caminho in pdfs:
        try:
            itens.extend(extrair_pdf(caminho, course_id))
        except Exception:
            logger.exception("Falha ao extrair %s (curso %s).", caminho.name, course_id)
    return itens
