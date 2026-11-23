"""Testes do nó do LangGraph do gerador de questões.

O nó chama gerar_questoes() com o RAG e o LLM de verdade; aqui os dois são
trocados por falsos com monkeypatch, para nada usar rede.
"""

from functools import partial

import pytest
from dubles_gerador import (
    TRECHO_FRACO,
    TRECHOS,
    BuscarFalso,
    LLMFalso,
    questao_dissertativa,
    questao_multipla,
    resposta,
)
from langgraph.graph import END, START, StateGraph
from src.agente_gerador import node, service
from src.state import GlauxState


def cinco_questoes():
    """Resposta válida para um pedido de 5 questões."""
    return resposta(
        questao_multipla(1, TRECHOS[0]),
        questao_dissertativa(2, TRECHOS[1]),
        questao_multipla(3, TRECHOS[2]),
        questao_dissertativa(4, TRECHOS[0]),
        questao_multipla(5, TRECHOS[1]),
    )


def trocar_dependencias(monkeypatch, buscar, llm):
    falso = partial(service.gerar_questoes, buscar=buscar, chamar_llm=llm)
    monkeypatch.setattr(node, "gerar_questoes", falso)


def estado(**campos) -> GlauxState:
    return GlauxState(user_id="aluno-teste", **campos)


def test_no_grava_as_questoes_e_o_status(monkeypatch):
    buscar, llm = BuscarFalso(TRECHOS), LLMFalso(cinco_questoes())
    trocar_dependencias(monkeypatch, buscar, llm)

    saida = node.gerador_questoes_node(
        estado(tema="overfitting", curso_alvo=42, quantidade_questoes=5)
    )

    assert set(saida) == {"generated_questions", "generation_status", "generation_message"}
    assert saida["generation_status"] == "ok"
    assert saida["generation_message"] is None
    assert len(saida["generated_questions"]) == 5
    assert all(isinstance(q, dict) for q in saida["generated_questions"])
    assert saida["generated_questions"][0]["trecho_referencia"]["texto"] == TRECHOS[0]["texto"]
    assert buscar.chamadas == [{"pergunta": "overfitting", "course_id": 42, "k": 5}]


@pytest.mark.parametrize(
    "campos",
    [
        {"tema": None, "curso_alvo": 42},
        {"tema": "   ", "curso_alvo": 42},
        {"tema": "overfitting", "curso_alvo": None},
        {},
    ],
)
def test_no_sem_tema_ou_disciplina_nao_chama_nada(monkeypatch, campos):
    buscar, llm = BuscarFalso(TRECHOS), LLMFalso()
    trocar_dependencias(monkeypatch, buscar, llm)

    saida = node.gerador_questoes_node(estado(quantidade_questoes=5, **campos))

    assert saida == {
        "generated_questions": [],
        "generation_status": "erro",
        "generation_message": node.MENSAGEM_SEM_ALVO,
    }
    assert buscar.chamadas == []
    assert llm.chamadas == []


def test_no_sem_quantidade_nao_muda_o_estado(monkeypatch):
    buscar, llm = BuscarFalso(TRECHOS), LLMFalso()
    trocar_dependencias(monkeypatch, buscar, llm)

    saida = node.gerador_questoes_node(estado(tema="overfitting", curso_alvo=42))

    assert saida == {}
    assert buscar.chamadas == []
    assert llm.chamadas == []


@pytest.mark.parametrize("quantidade", [0, -1, service.TETO_QUESTOES + 1])
def test_no_com_quantidade_fora_do_limite_grava_erro(monkeypatch, quantidade):
    buscar, llm = BuscarFalso(TRECHOS), LLMFalso()
    trocar_dependencias(monkeypatch, buscar, llm)

    saida = node.gerador_questoes_node(
        estado(tema="overfitting", curso_alvo=42, quantidade_questoes=quantidade)
    )

    assert saida == {
        "generated_questions": [],
        "generation_status": "erro",
        "generation_message": node.MENSAGEM_QUANTIDADE_INVALIDA,
    }
    assert buscar.chamadas == []
    assert llm.chamadas == []


def test_no_repassa_a_quantidade_pedida(monkeypatch):
    duas = resposta(questao_multipla(1, TRECHOS[0]), questao_dissertativa(2, TRECHOS[1]))
    trocar_dependencias(monkeypatch, BuscarFalso(TRECHOS), LLMFalso(duas))

    saida = node.gerador_questoes_node(
        estado(tema="overfitting", curso_alvo=42, quantidade_questoes=2)
    )

    assert saida["generation_status"] == "ok"
    assert len(saida["generated_questions"]) == 2


def test_no_repassa_sem_material(monkeypatch):
    llm = LLMFalso()
    trocar_dependencias(monkeypatch, BuscarFalso([TRECHO_FRACO]), llm)

    saida = node.gerador_questoes_node(estado(tema="grafos", curso_alvo=42, quantidade_questoes=5))

    assert saida["generation_status"] == "sem_material"
    assert saida["generated_questions"] == []
    assert "Procure o professor" in saida["generation_message"]
    assert llm.chamadas == []


def test_no_funciona_dentro_de_um_grafo_langgraph(monkeypatch):
    trocar_dependencias(monkeypatch, BuscarFalso(TRECHOS), LLMFalso(cinco_questoes()))

    grafo = StateGraph(GlauxState)
    grafo.add_node("gerador_questoes", node.gerador_questoes_node)
    grafo.add_edge(START, "gerador_questoes")
    grafo.add_edge("gerador_questoes", END)
    final = grafo.compile().invoke(estado(tema="overfitting", curso_alvo=42, quantidade_questoes=5))

    assert final["generation_status"] == "ok"
    assert len(final["generated_questions"]) == 5
    assert final["tema"] == "overfitting"  # o resto do estado continua lá
