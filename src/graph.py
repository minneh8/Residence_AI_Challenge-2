# src/graph.py
import argparse
import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from langgraph.graph import END, START, StateGraph
from src.agente_canvas.node import canvas_agent_node
from src.agente_canvas.service import CanvasAuthError
from src.agente_tutor.node import tutor_agent_node
from src.agente_tutor.service import frases_sem_citacao
from src.state import GlauxState


def _formatar_fontes(fontes: list) -> str:
    """Formata sources_used (List[Dict]) como "[arquivo, p.X-Y]"."""
    partes = []
    for f in fontes:
        if isinstance(f, dict):
            partes.append(f"[{f.get('arquivo')}, p.{f.get('pagina')}-{f.get('pagina_fim')}]")
        else:
            partes.append(str(f))
    return ", ".join(partes) if partes else "nenhuma"


def build_glaux_graph():
    """Constrói o grafo orquestrador dos agentes do Projeto Glaux."""
    workflow = StateGraph(GlauxState)

    workflow.add_node("canvas_agent", canvas_agent_node)
    workflow.add_node("tutor_agent", tutor_agent_node)

    workflow.add_edge(START, "canvas_agent")
    workflow.add_edge("canvas_agent", "tutor_agent")
    workflow.add_edge("tutor_agent", END)

    return workflow.compile()


def main() -> int:
    parser = argparse.ArgumentParser(description="Esteira Glaux: Canvas + RAG + Tutor.")
    parser.add_argument(
        "--tema", type=str, default=None,
        help="consulta única do Tutor (substitui as consultas por tarefa).",
    )
    parser.add_argument(
        "--curso", type=int, default=None,
        help="id do curso: roda a esteira (Canvas e Tutor) só nesse curso.",
    )
    args = parser.parse_args()

    load_dotenv()
    sys.stdout.reconfigure(errors="replace")

    initial_state = GlauxState(
        user_id="estudante_glaux",
        canvas_api_key=os.getenv("CANVAS_API_KEY"),
        tema=args.tema,
        curso_alvo=args.curso,
    )

    print(" Executando esteira completa do Glaux...\n")
    inicio = time.perf_counter()
    app = build_glaux_graph()
    try:
        final_state = app.invoke(initial_state)
    except CanvasAuthError as e:
        print(f"\n [ERRO] {e}")
        return 1

    # --------------------------------------------------------------------------
    #  CRONOGRAMA DE TAREFAS
    # --------------------------------------------------------------------------
    print("\n================  CRONOGRAMA DE TAREFAS ================")
    assignments = final_state.get("assignments", [])
    for task in assignments:
        t = task if isinstance(task, dict) else task.model_dump()
        dias = t.get("days_remaining")
        dias_str = f"{dias} dias restantes" if dias is not None else "Sem prazo"
        print(f"[{t.get('priority_level')}] {t.get('course_name')} | {t.get('title')}")
        print(f"    {dias_str} | {t.get('action_recommendation')}\n")

    # --------------------------------------------------------------------------
    #  RESUMOS DAS MATÉRIAS (+ auditoria de citações)
    # --------------------------------------------------------------------------
    print("\n================  RESUMOS DAS MATÉRIAS ================")
    summaries = final_state.get("summaries", [])
    for summary in summaries:
        s = summary if isinstance(summary, dict) else summary.model_dump()
        print(f"\n Disciplina: {s.get('course_name')}")
        print(f" Título: {s.get('topic_title')}")
        print(f" Fontes Utilizadas: {_formatar_fontes(s.get('sources_used', []))}")
        print("--- CONTEÚDO DO RESUMO ---")
        print(s.get("summary_text"))
        sem_citacao = frases_sem_citacao(s.get("summary_text", ""))
        if sem_citacao:
            print(f"--- ⚠️ FRASES SEM CITAÇÃO ({len(sem_citacao)}) ---")
            for frase in sem_citacao:
                print(f"    • {frase}")
        print("------------------------------------------------------------------")

    # --------------------------------------------------------------------------
    #  SALVA O RESULTADO DO TUTOR EM JSON
    # --------------------------------------------------------------------------
    output_path = Path("data/processed/tutor_output.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    clean_output = {
        "user_id": final_state.get("user_id"),
        "courses": final_state.get("courses", []),
        "assignments": final_state.get("assignments", []),
        "summaries": final_state.get("summaries", []),
        "downloaded_files": final_state.get("downloaded_files", []),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(clean_output, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n Saída do Agente Tutor salva em: {output_path}")
    print(f" Tempo total: {time.perf_counter() - inicio:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())