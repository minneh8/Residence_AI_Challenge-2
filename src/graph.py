# src/graph.py
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict
from dotenv import load_dotenv

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from langgraph.graph import END, START, StateGraph
from src.state import GlauxState
from src.agente_orquestrador.node import (
    orchestrator_node,
    rag_index_node,
    route_from_orchestrator,
)
from src.agente_canvas.node import canvas_agent_node
from src.agente_tutor.node import tutor_agent_node

try:
    from src.agente_gerador.node import question_generator_node
except ImportError:
    def question_generator_node(state: GlauxState) -> Dict[str, Any]:
        print("[Agente Gerador] Modulo ainda nao plugado; mantendo estado atual.")
        return {}


def build_glaux_graph():
    """Constroi e compila o grafo dinamico orquestrado do Projeto Glaux."""
    workflow = StateGraph(GlauxState)

    # 1. Registra todos os nos
    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("canvas_agent", canvas_agent_node)
    workflow.add_node("rag_index_node", rag_index_node)
    workflow.add_node("tutor_agent", tutor_agent_node)
    workflow.add_node("question_generator_agent", question_generator_node)

    # 2. Entrada sempre passa pelo Orquestrador
    workflow.add_edge(START, "orchestrator")

    # 3. Roteamento condicional a partir do Orquestrador
    workflow.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {
            "canvas_agent": "canvas_agent",
            "rag_index_node": "rag_index_node",
            "tutor_agent": "tutor_agent",
            "question_generator_agent": "question_generator_agent",
            "END": END,
        },
    )

    # 4. Todos os nos devolvem o controle ao Orquestrador ao concluir
    workflow.add_edge("canvas_agent", "orchestrator")
    workflow.add_edge("rag_index_node", "orchestrator")
    workflow.add_edge("tutor_agent", "orchestrator")
    workflow.add_edge("question_generator_agent", "orchestrator")

    return workflow.compile()


if __name__ == "__main__":
    load_dotenv()

    app = build_glaux_graph()
    initial_state = GlauxState(
        user_id="estudante_glaux",
        canvas_api_key=os.getenv("CANVAS_API_KEY"),
        action="FLUXO_COMPLETO",
    )

    print("Iniciando execucao orquestrada do Projeto Glaux...\n")
    final_state = app.invoke(initial_state)

    # Remove credenciais sensiveis antes de salvar em disco
    safe_output = {k: v for k, v in final_state.items() if k != "canvas_api_key"}

    output_path = Path("data/processed/tutor_output.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(safe_output, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nSaida salva com seguranca em: {output_path}")