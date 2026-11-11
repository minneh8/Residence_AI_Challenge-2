"""Geração de embeddings e gravação dos chunks no índice vetorial.

O índice fica persistido em data/chroma/ (ChromaDB). Cada configuração de
chunking tem sua própria coleção, "rag_j<janela>_s<sobreposicao>", e todas
as coleções usam distância de cosseno.

Em cada coleção:
    id          chunk_id (ver chunking.gerar_chunks)
    documento   texto do chunk, SEM o prefixo "passage: "
    metadados   arquivo, pagina, pagina_fim, course_id, caracteres

Reindexar um curso apaga antes os chunks daquele course_id na coleção,
então rodar a indexação de novo não duplica nada.
"""

import json
import logging
import time
from functools import lru_cache
from pathlib import Path

from .chunking import filtrar_paginas, gerar_chunks
from .embeddings import embeddings_passages
from .extracao import extrair_curso, listar_pdfs

logger = logging.getLogger(__name__)

# Raiz do repositório (src/rag/indexacao.py -> parents[2]).
RAIZ_REPO = Path(__file__).resolve().parents[2]
DIR_DADOS = RAIZ_REPO / "data"
DIR_CHROMA = DIR_DADOS / "chroma"

# Registro do que já foi indexado, para pular a reindexação quando a lista de
# PDFs e suas datas de modificação não mudarem. Fica em data/ (fora do git).
ARQ_MANIFEST = DIR_DADOS / "indice_manifest.json"

METADADOS_CHUNK = ("arquivo", "pagina", "pagina_fim", "course_id", "caracteres")
TAMANHO_LOTE_GRAVACAO = 1000


def nome_colecao(janela: int, sobreposicao: int) -> str:
    return f"rag_j{janela}_s{sobreposicao}"


@lru_cache(maxsize=1)
def _cliente():
    """Cliente persistente do ChromaDB, criado uma vez por processo."""
    import chromadb
    from chromadb.config import Settings

    DIR_CHROMA.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(DIR_CHROMA), settings=Settings(anonymized_telemetry=False))


def obter_colecao(nome: str, criar: bool = False):
    """Abre a coleção `nome`. Sem `criar`, retorna None se ela não existir.

    embedding_function=None: os embeddings são sempre calculados aqui
    (embeddings.py), nunca pelo ChromaDB.
    """
    cliente = _cliente()
    if criar:
        colecao = cliente.get_or_create_collection(
            nome, metadata={"hnsw:space": "cosine"}, embedding_function=None)
        espaco = (colecao.metadata or {}).get("hnsw:space")
        if espaco != "cosine":
            raise ValueError(f"A coleção {nome} existe com distância {espaco!r}, não cosseno.")
        return colecao
    if nome not in {c if isinstance(c, str) else c.name for c in cliente.list_collections()}:
        return None
    return cliente.get_collection(nome, embedding_function=None)


def _assinatura_pdfs(pdfs: list[Path]) -> dict:
    """Mapa {nome do PDF: data de modificação em ns}, ordenado por nome."""
    return {
        p.name: p.stat().st_mtime_ns
        for p in sorted(pdfs, key=lambda p: p.name.lower())
    }


def _registro_atual(colecao: str, janela: int, sobreposicao: int,
                    pdfs: list[Path]) -> dict:
    """Assinatura do que seria indexado: coleção, parâmetros e PDFs+mtimes."""
    return {
        "colecao": colecao,
        "janela": janela,
        "sobreposicao": sobreposicao,
        "pdfs": _assinatura_pdfs(pdfs),
    }


def _carregar_manifest() -> dict:
    try:
        with open(ARQ_MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _salvar_manifest(manifest: dict) -> None:
    ARQ_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    temporario = ARQ_MANIFEST.with_suffix(".json.tmp")
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    temporario.replace(ARQ_MANIFEST)


def _resultado_vazio(course_id: int, colecao: str, pdfs: int, paginas: int,
                     inicio: float, aviso: str) -> dict:
    logger.warning(aviso)
    return {
        "course_id": course_id,
        "colecao": colecao,
        "pdfs": pdfs,
        "paginas_mantidas": paginas,
        "chunks": 0,
        "tempo_s": round(time.perf_counter() - inicio, 2),
        "pulado": False,
        "aviso": aviso,
    }


def indexar_curso(course_id: int, janela: int = 1, sobreposicao: int = 0,
                  forcar: bool = False) -> dict:
    """Extrai, divide e indexa os PDFs de data/raw/<course_id>/.

    Usa gerar_chunks (com o limite de tokens do chunking) e grava na coleção
    nome_colecao(janela, sobreposicao). Os chunks antigos do mesmo course_id
    são apagados só depois que os novos embeddings ficam prontos.

    O padrão janela=1, sobreposicao=0 corresponde a COLECAO_PADRAO (rag_j1_s0),
    a coleção consultada por src.rag.buscar.

    A reindexação é pulada quando a lista de PDFs e suas datas de modificação
    não mudaram desde a última indexação (registro em data/indice_manifest.json)
    e o curso ainda está presente na coleção. Use forcar=True para reindexar
    mesmo assim.

    Returns:
        {"course_id", "colecao", "pdfs", "paginas_mantidas", "chunks",
         "tempo_s", "pulado", "aviso"}. "pulado" é True quando a reindexação
        foi dispensada por falta de mudanças. "aviso" é None quando tudo foi
        indexado. Se o curso não tiver PDFs (ou nenhum chunk), "chunks" é 0,
        "aviso" explica o motivo e o índice não é alterado.

    Raises:
        ValueError: se janela/sobreposicao forem inválidas (ver gerar_chunks).
    """
    inicio = time.perf_counter()
    gerar_chunks([], janela, sobreposicao)  # valida os parâmetros antes de qualquer trabalho
    colecao_nome = nome_colecao(janela, sobreposicao)

    try:
        pdfs = listar_pdfs(course_id)
    except FileNotFoundError:
        pdfs = []
    if not pdfs:
        return _resultado_vazio(
            course_id, colecao_nome, 0, 0, inicio,
            f"Curso {course_id} sem PDFs em data/raw/{course_id}/; nada foi indexado.")

    # Pula a reindexação se nada mudou e o curso ainda está na coleção.
    registro = _registro_atual(colecao_nome, janela, sobreposicao, pdfs)
    manifest = _carregar_manifest()
    if not forcar and manifest.get(str(course_id)) == registro:
        colecao = obter_colecao(colecao_nome)
        if colecao is not None:
            ids = colecao.get(where={"course_id": course_id}, include=[])["ids"]
            if ids:
                logger.info("Curso %s sem mudanças; reindexação pulada.", course_id)
                return {
                    "course_id": course_id,
                    "colecao": colecao_nome,
                    "pdfs": len(pdfs),
                    "paginas_mantidas": None,
                    "chunks": len(ids),
                    "tempo_s": round(time.perf_counter() - inicio, 2),
                    "pulado": True,
                    "aviso": None,
                }

    paginas = extrair_curso(course_id)
    mantidas, _ = filtrar_paginas(paginas)
    chunks = gerar_chunks(paginas, janela=janela, sobreposicao=sobreposicao)
    if not chunks:
        return _resultado_vazio(
            course_id, colecao_nome, len(pdfs), len(mantidas), inicio,
            f"Curso {course_id} não gerou chunks (todas as páginas descartadas); "
            "nada foi indexado.")

    vetores = embeddings_passages([c["texto"] for c in chunks])

    colecao = obter_colecao(colecao_nome, criar=True)
    colecao.delete(where={"course_id": course_id})
    for i in range(0, len(chunks), TAMANHO_LOTE_GRAVACAO):
        lote = chunks[i:i + TAMANHO_LOTE_GRAVACAO]
        colecao.add(
            ids=[c["chunk_id"] for c in lote],
            documents=[c["texto"] for c in lote],
            embeddings=vetores[i:i + TAMANHO_LOTE_GRAVACAO],
            metadatas=[{k: c[k] for k in METADADOS_CHUNK} for c in lote],
        )

    manifest[str(course_id)] = registro
    _salvar_manifest(manifest)

    return {
        "course_id": course_id,
        "colecao": colecao_nome,
        "pdfs": len(pdfs),
        "paginas_mantidas": len(mantidas),
        "chunks": len(chunks),
        "tempo_s": round(time.perf_counter() - inicio, 2),
        "pulado": False,
        "aviso": None,
    }
