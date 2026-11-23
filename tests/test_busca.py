# tests/test_busca.py
"""Testes offline do filtro por categoria em src.rag.busca.

Usa uma coleção do ChromaDB em memória (sem data/chroma) e embeddings fixos
(sem carregar o modelo E5).
"""

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from src.rag import busca  # noqa: E402

CURSO = 93527
OUTRO_CURSO = 93511


@pytest.fixture
def colecao(monkeypatch):
    import chromadb
    from chromadb.config import Settings

    cliente = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    col = cliente.create_collection(f"teste_{uuid.uuid4().hex}", metadata={"hnsw:space": "cosine"},
                                    embedding_function=None)
    chunks = [
        ("s1", "aula03.pdf", "slides", CURSO, [1.0, 0.0, 0.0]),
        ("s2", "aula04.pdf", "slides", CURSO, [0.9, 0.1, 0.0]),
        ("l1", "lista_exercicios_01.pdf", "listas", CURSO, [0.99, 0.01, 0.0]),
        ("t1", "roteiro.pdf", "trabalho", CURSO, [0.95, 0.05, 0.0]),
        ("x1", "pmbok.pdf", "livros", OUTRO_CURSO, [1.0, 0.0, 0.0]),
    ]
    col.add(
        ids=[c[0] for c in chunks],
        documents=[f"texto {c[0]}" for c in chunks],
        embeddings=[c[4] for c in chunks],
        metadatas=[{"arquivo": c[1], "pagina": 1, "pagina_fim": 1, "course_id": c[3],
                    "caracteres": 10, "categoria": c[2]} for c in chunks],
    )
    monkeypatch.setattr(busca, "obter_colecao", lambda nome: col)
    monkeypatch.setattr(busca, "embedding_query", lambda texto: [1.0, 0.0, 0.0])
    return col


def test_filtro_where_sem_categorias():
    assert busca.filtro_where(CURSO) == {"course_id": CURSO}
    assert busca.filtro_where(CURSO, None) == {"course_id": CURSO}


def test_filtro_where_com_categorias():
    assert busca.filtro_where(CURSO, ["slides", "listas"]) == {"$and": [
        {"course_id": CURSO},
        {"categoria": {"$in": ["slides", "listas"]}},
    ]}


def test_sem_categorias_busca_todas_do_curso(colecao):
    trechos = busca.buscar("pergunta", CURSO, k=10)
    assert {t["arquivo"] for t in trechos} == {
        "aula03.pdf", "aula04.pdf", "lista_exercicios_01.pdf", "roteiro.pdf"}


def test_categorias_slides_so_traz_slides(colecao):
    trechos = busca.buscar("pergunta", CURSO, k=10, categorias=["slides"])
    assert [t["arquivo"] for t in trechos] == ["aula03.pdf", "aula04.pdf"]


def test_varias_categorias(colecao):
    trechos = busca.buscar("pergunta", CURSO, k=10, categorias=["listas", "slides"])
    assert {t["arquivo"] for t in trechos} == {"aula03.pdf", "aula04.pdf", "lista_exercicios_01.pdf"}


def test_filtro_nao_vaza_outro_curso(colecao):
    assert busca.buscar("pergunta", CURSO, k=10, categorias=["livros"]) == []


def test_k_limita_depois_do_filtro(colecao):
    # Sem filtro, a lista (0.99) ficaria em 2º; com o filtro, o 2º é aula04.
    trechos = busca.buscar("pergunta", CURSO, k=2, categorias=["slides"])
    assert [t["arquivo"] for t in trechos] == ["aula03.pdf", "aula04.pdf"]


@pytest.mark.parametrize("categorias", [[], "slides", [""], [None]])
def test_categorias_invalidas(colecao, categorias):
    with pytest.raises(ValueError):
        busca.buscar("pergunta", CURSO, k=3, categorias=categorias)
