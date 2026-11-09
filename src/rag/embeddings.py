"""Modelo de embeddings compartilhado pela indexação e pela busca.

O modelo E5 espera prefixos diferentes para documentos e perguntas:
    "passage: <texto>"   ao indexar (indexacao.py)
    "query: <pergunta>"  ao buscar (busca.py)

Os prefixos só entram no cálculo do embedding; o texto salvo no índice
não os contém. Os vetores saem normalizados (norma 1), então a distância
de cosseno do ChromaDB equivale a 1 - produto interno.
"""

from functools import lru_cache

# O mesmo modelo cujo tokenizador o chunking usa para limitar os tokens.
from .chunking import MODELO_TOKENIZADOR as MODELO_EMBEDDINGS
from .chunking import PREFIXO_PASSAGE

PREFIXO_QUERY = "query: "
TAMANHO_LOTE = 16


@lru_cache(maxsize=1)
def carregar_modelo():
    """Carrega o SentenceTransformer uma única vez por processo."""
    # Import tardio: importar src.rag (ex.: só para buscar a assinatura)
    # não carrega torch/sentence-transformers.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODELO_EMBEDDINGS)


def embeddings_passages(textos: list[str]) -> list[list[float]]:
    """Embeddings normalizados de "passage: <texto>" para cada texto."""
    vetores = carregar_modelo().encode(
        [PREFIXO_PASSAGE + t for t in textos],
        batch_size=TAMANHO_LOTE,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vetores.tolist()


def embedding_query(pergunta: str) -> list[float]:
    """Embedding normalizado de "query: <pergunta>"."""
    vetor = carregar_modelo().encode(
        PREFIXO_QUERY + pergunta,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vetor.tolist()
