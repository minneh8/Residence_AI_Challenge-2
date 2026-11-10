# src/graph.py
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from langgraph.graph import END, START, StateGraph
from src.agente_canvas.node import canvas_agent_node
from src.agente_tutor.node import tutor_agent_node
from src.state import GlauxState


def build_glaux_graph():
    """Constrói o grafo orquestrador dos agentes do Projeto Glaux."""
    workflow = StateGraph(GlauxState)

    workflow.add_node("canvas_agent", canvas_agent_node)
    workflow.add_node("tutor_agent", tutor_agent_node)

    workflow.add_edge(START, "canvas_agent")
    workflow.add_edge("canvas_agent", "tutor_agent")
    workflow.add_edge("tutor_agent", END)

    return workflow.compile()


if __name__ == "__main__":
    load_dotenv()

    app = build_glaux_graph()
    initial_state = GlauxState(
        user_id="estudante_glaux", canvas_api_key=os.getenv("CANVAS_API_KEY")
    )

    print(" Executando esteira completa do Glaux...\n")
    final_state = app.invoke(initial_state)

    # --------------------------------------------------------------------------
    #  EXIBIÇÃO FORMATADA NO TERMINAL
    # --------------------------------------------------------------------------
    print("\n================  CRONOGRAMA DE TAREFAS ================")
    assignments = final_state.get("assignments", [])
    for task in assignments:
        t = task if isinstance(task, dict) else task.model_dump()
        dias = t.get("days_remaining")
        dias_str = f"{dias} dias restantes" if dias is not None else "Sem prazo"
        print(f"[{t.get('priority_level')}] {t.get('course_name')} | {t.get('title')}")
        print(f"    {dias_str} | {t.get('action_recommendation')}\n")

    print("\n================  RESUMOS DAS MATÉRIAS ================")
    summaries = final_state.get("summaries", [])
    for summary in summaries:
        s = summary if isinstance(summary, dict) else summary.model_dump()
        print(f"\n Disciplina: {s.get('course_name')}")
        print(f" Título: {s.get('topic_title')}")
        print(f" Fontes Utilizadas: {', '.join(s.get('sources_used', []))}")
        print("--- CONTEÚDO DO RESUMO ---")
        print(s.get("summary_text"))
        print("------------------------------------------------------------------")

    # --------------------------------------------------------------------------
    # SALVA O RESULTADO DO TUTOR EM JSON NA PASTA PROCESSED
    # --------------------------------------------------------------------------
    output_path = Path("data/processed/tutor_output.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_state, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n Saída do Agente Tutor salva em: {output_path}")