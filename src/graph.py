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
from src.agente_canvas.service import CanvasAuthError
from src.agente_gerador.apresentacao import formatar, resultado_do_estado
from src.agente_gerador.node import gerador_questoes_node
from src.agente_gerador.service import TETO_QUESTOES
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
    # Sem --questoes, o gerador devolve {} e não chama nem o RAG nem o LLM.
    workflow.add_node("gerador_questoes", gerador_questoes_node)

    workflow.add_edge(START, "canvas_agent")
    workflow.add_edge("canvas_agent", "tutor_agent")
    workflow.add_edge("tutor_agent", "gerador_questoes")
    workflow.add_edge("gerador_questoes", END)

    return workflow.compile()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Esteira Glaux: Canvas + RAG + Tutor + Gerador de Questões."
    )
    parser.add_argument(
        "--tema", type=str, default=None,
        help="consulta única do Tutor (substitui as consultas por tarefa).",
    )
    parser.add_argument(
        "--curso", type=int, default=None,
        help="id do curso: roda a esteira (Canvas e Tutor) só nesse curso.",
    )
    parser.add_argument(
        "--questoes", type=int, default=None, metavar="N",
        help=f"gera N questões (1 a {TETO_QUESTOES}) sobre --tema no --curso.",
    )
    args = parser.parse_args()
    if args.questoes is not None:
        if args.tema is None or args.curso is None:
            parser.error("--questoes exige --tema e --curso.")
        if not 1 <= args.questoes <= TETO_QUESTOES:
            parser.error(f"--questoes deve ser um número de 1 a {TETO_QUESTOES}.")

    load_dotenv()

    app = build_glaux_graph()
    initial_state = GlauxState(
        user_id="estudante_glaux",
        canvas_api_key=os.getenv("CANVAS_API_KEY"),
        action="FLUXO_COMPLETO",
        tema=args.tema,
        curso_alvo=args.curso,
        quantidade_questoes=args.questoes,
    )

    print("Iniciando execucao orquestrada do Projeto Glaux...\n")
    final_state = app.invoke(initial_state)

    # Remove credenciais sensiveis antes de salvar em disco
    safe_output = {k: v for k, v in final_state.items() if k != "canvas_api_key"}

    output_path = Path("data/processed/tutor_output.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(safe_output, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n Saída do Agente Tutor salva em: {output_path}")

    # --------------------------------------------------------------------------
    #  QUESTÕES DE ESTUDO (só com --questoes)
    # --------------------------------------------------------------------------
    resultado_questoes = resultado_do_estado(final_state)
    if resultado_questoes is not None:
        print("\n================  QUESTÕES DE ESTUDO ================")
        print(formatar(resultado_questoes))
        questoes_path = Path("data/processed/questoes_output.json")
        questoes_path.parent.mkdir(parents=True, exist_ok=True)
        questoes_output = {
            "tema": final_state.get("tema"),
            "curso_alvo": final_state.get("curso_alvo"),
            "quantidade_questoes": final_state.get("quantidade_questoes"),
            "generation_status": final_state.get("generation_status"),
            "generation_message": final_state.get("generation_message"),
            "generated_questions": final_state.get("generated_questions", []),
        }
        with open(questoes_path, "w", encoding="utf-8") as f:
            json.dump(questoes_output, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n Questões salvas em: {questoes_path}")

    print(f" Tempo total: {time.perf_counter() - inicio:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
