"""Geração de embeddings e gravação dos chunks no índice vetorial.

O índice fica persistido em data/chroma/.

Ainda não implementado.
"""

from pathlib import Path

# Raiz do repositório (src/rag/indexacao.py -> parents[2]).
RAIZ_REPO = Path(__file__).resolve().parents[2]
DIR_CHROMA = RAIZ_REPO / "data" / "chroma"


def indexar_curso(course_id: int) -> int:
    """Extrai, divide e indexa os PDFs de data/raw/<course_id>/.

    Retorna a quantidade de chunks indexados.
    """
    raise NotImplementedError
