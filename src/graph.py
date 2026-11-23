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
from src.agente_gerador.apresentacao import formatar, resultado_do_estado
from src.agente_gerador.node import gerador_questoes_node
from src.agente_gerador.service import TETO_QUESTOES
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
    sys.stdout.reconfigure(errors="replace")

    initial_state = GlauxState(
        user_id="estudante_glaux",
        canvas_api_key=os.getenv("CANVAS_API_KEY"),
        tema=args.tema,
        curso_alvo=args.curso,
        quantidade_questoes=args.questoes,
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