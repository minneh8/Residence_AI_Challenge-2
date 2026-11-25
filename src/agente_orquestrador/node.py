# src/agente_orquestrador/node.py
import sys
from pathlib import Path
from typing import Any, Dict, List

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from src.state import GlauxState
from src.agente_orquestrador.service import OrchestratorService


def orchestrator_node(state: GlauxState) -> Dict[str, Any]:
    """
    No supervisor do LangGraph.
    Na primeira entrada, constroi o plano de execucao.
    Nas entradas seguintes, consome a fila ate concluir todas as etapas.
    """
    service = OrchestratorService()
    logs: List[str] = list(state.orchestrator_logs)

    # 1. Inicializacao do plano na primeira entrada do grafo
    if not state.plan_initialized:
        plan = service.build_execution_plan(state)
        fila = list(plan.steps)

        header_log = (
            f"[Orquestrador] Acao='{state.action}' | "
            f"CursoAlvo={plan.resolved_course_id} | "
            f"Plano={fila} | Motivo: {plan.reason}"
        )
        print(f"\n{header_log}")
        logs.append(header_log)

        if not fila:
            return {
                "plan_initialized": True,
                "execution_plan": [],
                "next_node": "END",
                "curso_alvo": plan.resolved_course_id,
                "orchestrator_logs": logs,
            }

        proximo = fila.pop(0)
        step_log = f"[Orquestrador] Despachando primeiro no -> {proximo}"
        print(step_log)
        logs.append(step_log)

        return {
            "plan_initialized": True,
            "execution_plan": fila,
            "next_node": proximo,
            "curso_alvo": plan.resolved_course_id,
            "orchestrator_logs": logs,
        }

    # 2. Retorno de um agente: verifica se ainda ha etapas na fila
    fila_restante = list(state.execution_plan)
    if fila_restante:
        proximo = fila_restante.pop(0)
        step_log = f"[Orquestrador] Etapa concluida. Despachando proximo no -> {proximo}"
        print(f"\n{step_log}")
        logs.append(step_log)

        return {
            "execution_plan": fila_restante,
            "next_node": proximo,
            "orchestrator_logs": logs,
        }

    # 3. Fila vazia: finaliza a execucao do grafo
    end_log = "[Orquestrador] Plano concluido com sucesso. Encerrando grafo (END)."
    print(f"\n{end_log}")
    logs.append(end_log)

    return {
        "execution_plan": [],
        "next_node": "END",
        "orchestrator_logs": logs,
    }


def route_from_orchestrator(state: GlauxState) -> str:
    """Funcao de roteamento usada em workflow.add_conditional_edges no src/graph.py."""
    return state.next_node or "END"


def rag_index_node(state: GlauxState) -> Dict[str, Any]:
    """
    No responsavel por garantir que os PDFs de data/raw/<course_id>/conteudo/
    estejam indexados na base vetorial (ChromaDB) antes da consulta do Tutor/Gerador.
    """
    from src.rag.indexacao import indexar_curso

    raw_dir = Path("data/raw")
    indexed_ids: List[int] = list(state.rag_indexed_courses)
    course_ids: List[int] = []

    if state.curso_alvo is not None:
        course_ids = [state.curso_alvo]
    elif state.courses:
        course_ids = [c.id if hasattr(c, "id") else c["id"] for c in state.courses]
    elif raw_dir.exists():
        course_ids = [
            int(f.name) for f in raw_dir.iterdir()
            if f.is_dir() and f.name.isdigit()
        ]

    print(f"\n[RAG Node] Verificando indexacao vetorial para {len(course_ids)} disciplina(s)...")
    for cid in course_ids:
        try:
            res = indexar_curso(cid, forcar=state.force_sync)
            if res.get("pulado"):
                print(f" [RAG Node] Curso {cid}: ja atualizado ({res.get('chunks', 0)} chunks).")
            elif res.get("aviso"):
                print(f" [RAG Node] Curso {cid}: {res['aviso']}")
            else:
                print(f" [RAG Node] Curso {cid}: indexado com {res.get('chunks', 0)} chunks.")

            if cid not in indexed_ids:
                indexed_ids.append(cid)
        except Exception as e:
            print(f" [RAG Node] Erro ao indexar curso {cid}: {e}")

    return {"rag_indexed_courses": indexed_ids}