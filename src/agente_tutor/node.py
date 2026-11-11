# src/agente_tutor/node.py
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from src.state import GlauxState, CanvasCourse
from src.agente_tutor.service import TutorService


def tutor_agent_node(state: GlauxState) -> Dict[str, Any]:
    print("\n [Agente Tutor] Gerando cronograma de tarefas e resumos com RAG + LLM...")

    try:
        service = TutorService()
        courses = [CanvasCourse(**c) if isinstance(c, dict) else c for c in state.courses]

        # --curso <id>: restringe o Tutor a um único curso.
        if state.curso_alvo:
            courses = [c for c in courses if c.id == state.curso_alvo]

        # 1. Cronograma (todas as tarefas pendentes dos cursos em escopo)
        schedule = service.generate_schedule(courses)
        tarefas_por_curso = defaultdict(list)
        for tarefa in schedule:
            tarefas_por_curso[tarefa.course_id].append(tarefa)

        # 2. Resumos — uma consulta por curso, guiada por --tema ou pelas tarefas
        summaries = []
        for course in courses:
            summary = service.generate_summary_for_course(
                course.id,
                course.name,
                tarefas=tarefas_por_curso.get(course.id, []),
                tema=state.tema,
            )
            summaries.append(summary.model_dump())

        print(f" [Agente Tutor] Cronograma com {len(schedule)} entregas mapeadas.")
        print(f" [Agente Tutor] {len(summaries)} resumo(s) gerado(s).")

        return {
            "assignments": [s.model_dump() for s in schedule],
            "summaries": summaries,
        }
    except Exception as e:
        print(f" [Agente Tutor] Erro durante a execução: {e}")
        return {}
