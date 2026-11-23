"""Busca de trechos relevantes para uma pergunta.

Interface pública consumida pelos agentes:

    buscar(pergunta: str, course_id: int, k: int = 5,
           categorias: list[str] | None = None) -> list[dict]

`categorias` restringe a busca às categorias de material do Agente Canvas
(metadata "categoria" dos chunks: slides, listas, trabalho, livros, outros).
O Tutor usa ["slides"]; o Gerador deve usar ["listas"] (ou listas + slides).

Cada item retornado tem as chaves:
    texto      (str)   conteúdo do trecho
    arquivo    (str)   nome do PDF de origem
    pagina     (int)   primeira página do trecho no PDF (começando em 1)
    pagina_fim (int)   última página do trecho
    score      (float) similaridade de cosseno (1 - distância); maior = mais relevante

Os itens vêm ordenados por score decrescente, com no máximo k elementos.

Busca vetorial pura no ChromaDB (data/chroma/), filtrada por course_id.
Ainda não há busca híbrida, reranking nem score mínimo: os k mais próximos
voltam sempre, mesmo quando a pergunta não tem relação com o material.
"""

import logging

from .embeddings import embedding_query
from .indexacao import obter_colecao

logger = logging.getLogger(__name__)

# Coleção usada por buscar(). rag_j1_s0 (A) = chunks de 1 página, sem
# sobreposição. Escolhida pela avaliação (scripts/avaliar.py, curso 93527,
# 18 perguntas com resposta): com k=5, A teve Recall@5 de 0,778 e MRR de
# 0,657, contra 0,778 e 0,611 de rag_j3_s1 (B), e cita 1 página por resultado
# (B cita cerca de 3,6). Com k=3, A também ficou à frente (0,778 contra 0,667).
COLECAO_PADRAO = "rag_j1_s0"


def _validar(pergunta: str, k: int, categorias) -> None:
    if not isinstance(pergunta, str) or not pergunta.strip():
        raise ValueError("A pergunta não pode ser vazia.")
    if k <= 0:
        raise ValueError("k deve ser maior que zero.")
    if categorias is not None:
        if isinstance(categorias, str) or not categorias \
                or not all(isinstance(c, str) and c for c in categorias):
            raise ValueError("categorias deve ser uma lista não vazia de nomes de categoria.")


def filtro_where(course_id: int, categorias=None) -> dict:
    """Filtro do Chroma: só course_id, ou $and de course_id e categoria $in."""
    if not categorias:
        return {"course_id": course_id}
    return {"$and": [
        {"course_id": course_id},
        {"categoria": {"$in": list(categorias)}},
    ]}


def buscar_na_colecao(pergunta: str, course_id: int, k: int, colecao: str,
                      categorias: list[str] | None = None) -> list[dict]:
    """Como buscar(), mas na coleção indicada. Útil para comparar configurações."""
    _validar(pergunta, k, categorias)

    col = obter_colecao(colecao)
    indexado = col is not None and col.get(
        where={"course_id": course_id}, limit=1, include=[])["ids"]
    if not indexado:
        logger.warning("Curso %s não está indexado na coleção %s.", course_id, colecao)
        return []

    resultado = col.query(
        query_embeddings=[embedding_query(pergunta.strip())],
        n_results=k,
        where=filtro_where(course_id, categorias),
        include=["documents", "metadatas", "distances"],
    )
    if categorias and not resultado["ids"][0]:
        logger.warning("Curso %s sem chunks das categorias %s na coleção %s.",
                       course_id, list(categorias), colecao)
    trechos = [
        {
            "texto": texto,
            "arquivo": meta["arquivo"],
            "pagina": meta["pagina"],
            "pagina_fim": meta["pagina_fim"],
            "score": 1 - distancia,
        }
        for texto, meta, distancia in zip(
            resultado["documents"][0], resultado["metadatas"][0], resultado["distances"][0])
    ]
    trechos.sort(key=lambda t: t["score"], reverse=True)
    return trechos


def buscar(pergunta: str, course_id: int, k: int = 5,
           categorias: list[str] | None = None) -> list[dict]:
    """Retorna os k trechos mais relevantes para a pergunta na disciplina.

    Args:
        pergunta: texto da pergunta do estudante. Não pode ser vazio.
        course_id: id da disciplina no Canvas.
        k: quantidade máxima de trechos retornados. Deve ser maior que zero.
        categorias: se informado, só trechos dessas categorias (ex.: ["slides"]).
            None (padrão) busca em todas.

    Returns:
        Lista de dicts com as chaves texto, arquivo, pagina, pagina_fim e
        score, ordenada por score decrescente. Lista vazia (com aviso no log)
        se o curso não estiver indexado em COLECAO_PADRAO.

    Raises:
        ValueError: se a pergunta for vazia (ou só espaços), se k <= 0 ou se
            categorias não for uma lista não vazia de strings.
    """
    return buscar_na_colecao(pergunta, course_id, k, COLECAO_PADRAO, categorias)
