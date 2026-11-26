"""A ligação do gerador com o RAG: ele usa a busca por categorias (buscar_para_gerador).

Tudo com falsos, sem Chroma, sem E5 e sem rede.
"""

import inspect

from dubles_gerador import TRECHOS
from src.agente_gerador import service
from src.rag import busca


def test_gerar_questoes_usa_por_padrao_a_busca_do_gerador():
    padrao = inspect.signature(service.gerar_questoes).parameters["buscar"].default

    assert padrao is busca.buscar_para_gerador


def test_busca_do_gerador_filtra_listas_slides_e_livros(monkeypatch):
    chamadas = []

    def buscar_falso(pergunta, course_id, k=5, categorias=None):
        chamadas.append(
            {"pergunta": pergunta, "course_id": course_id, "k": k, "categorias": categorias}
        )
        return list(TRECHOS)

    monkeypatch.setattr(busca, "buscar", buscar_falso)

    trechos = busca.buscar_para_gerador("camada de enlace", 42, k=10)

    assert trechos == TRECHOS
    assert chamadas == [
        {
            "pergunta": "camada de enlace",
            "course_id": 42,
            "k": 10,
            "categorias": ["listas", "slides", "livros"],
        }
    ]


def test_busca_do_gerador_aceita_a_assinatura_que_o_gerador_usa():
    # O gerador chama buscar(tema, course_id, k=...): é essa assinatura que os dublês imitam.
    parametros = list(inspect.signature(busca.buscar_para_gerador).parameters)

    assert parametros == ["pergunta", "course_id", "k"]
