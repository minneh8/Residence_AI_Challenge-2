"""Nó do LangGraph que gera as questões de estudo.

No LangGraph, cada nó recebe o estado e devolve só os campos que mudou; o grafo
junta essa resposta ao estado. Este nó só lê o estado, chama gerar_questoes()
e grava o resultado. A lógica fica em service.py, testável sem LangGraph.
"""

from typing import Any

from src.state import GlauxState

from .service import gerar_questoes

MENSAGEM_SEM_ALVO = "Não consegui gerar questões: faltou escolher o tema ou a disciplina."


def gerador_questoes_node(state: GlauxState) -> dict[str, Any]:
    """Gera questões sobre state.target_subject na disciplina state.target_course_id.

    Grava generated_questions (lista de dicts), generation_status e
    generation_message. Sem tema ou sem disciplina, grava "erro" e não chama
    nem o RAG nem o LLM. A quantidade é a padrão de gerar_questoes (5).
    """
    tema = (state.target_subject or "").strip()
    if not tema or state.target_course_id is None:
        return {
            "generated_questions": [],
            "generation_status": "erro",
            "generation_message": MENSAGEM_SEM_ALVO,
        }

    resultado = gerar_questoes(tema, state.target_course_id)
    return {
        "generated_questions": [questao.model_dump() for questao in resultado.questoes],
        "generation_status": resultado.status,
        "generation_message": resultado.mensagem,
    }
