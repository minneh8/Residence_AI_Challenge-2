"""Nó do LangGraph que gera as questões de estudo.

No LangGraph, cada nó recebe o estado e devolve só os campos que mudou; o grafo
junta essa resposta ao estado. Este nó só lê o estado, chama gerar_questoes()
e grava o resultado. A lógica fica em service.py, testável sem LangGraph.
"""

from typing import Any

from src.state import GlauxState

from .service import TETO_QUESTOES, gerar_questoes

MENSAGEM_SEM_ALVO = "Não consegui gerar questões: faltou escolher o tema ou a disciplina."
MENSAGEM_QUANTIDADE_INVALIDA = (
    f"Não consegui gerar questões: a quantidade deve ser um número de 1 a {TETO_QUESTOES}."
)


def gerador_questoes_node(state: GlauxState) -> dict[str, Any]:
    """Gera state.quantidade_questoes questões sobre state.tema no curso state.curso_alvo.

    Sem quantidade_questoes (o aluno não pediu --questoes), devolve {}: o estado
    não muda e nem o RAG nem o LLM são chamados. Com a quantidade, grava
    generated_questions (lista de dicts), generation_status e generation_message.
    Sem tema, sem curso ou com quantidade fora de 1 a TETO_QUESTOES, grava
    "erro" e não chama nada. A CLI já barra a quantidade; esta conferência
    protege quem chama o nó por fora dela, sem derrubar a esteira.
    """
    if state.quantidade_questoes is None:
        return {}

    tema = (state.tema or "").strip()
    if not tema or state.curso_alvo is None:
        return {
            "generated_questions": [],
            "generation_status": "erro",
            "generation_message": MENSAGEM_SEM_ALVO,
        }

    quantidade = state.quantidade_questoes
    if isinstance(quantidade, bool) or not 1 <= quantidade <= TETO_QUESTOES:
        return {
            "generated_questions": [],
            "generation_status": "erro",
            "generation_message": MENSAGEM_QUANTIDADE_INVALIDA,
        }

    resultado = gerar_questoes(tema, state.curso_alvo, quantidade)
    return {
        "generated_questions": [questao.model_dump() for questao in resultado.questoes],
        "generation_status": resultado.status,
        "generation_message": resultado.mensagem,
    }
