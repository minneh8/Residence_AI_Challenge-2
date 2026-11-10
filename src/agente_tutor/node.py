# src/agente_tutor/node.py
import sys
from pathlib import Path
from typing import Dict, Any

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from src.state import GlauxState, CanvasCourse
from src.agente_tutor.service import TutorService

def tutor_agent_node(state: GlauxState) -> Dict[str, Any]:
    print("\n [Agente Tutor] Gerando cronograma de tarefas e resumos com LLM...")

    try:
        service = TutorService()
        courses = [CanvasCourse(**c) if isinstance(c, dict) else c for c in state.courses]

        # 1. Gera Cronograma
        schedule = service.generate_schedule(courses)

        # 2. Gera Resumos das Matérias
        summaries = []
        for course in courses:
            summary = service.generate_summary_for_course(course.id, course.name)
            summaries.append(summary.model_dump())

        print(f" [Agente Tutor] Cronograma com {len(schedule)} entregas mapeadas.")
        print(f" [Agente Tutor] {len(summaries)} resumos gerados.")

        return {
            "assignments": [s.model_dump() for s in schedule],
            "summaries": summaries  # Certifique-se de usar a mesma chave definida no GlauxState
        }
    except Exception as e:
        print(f" [Agente Tutor] Erro durante a execução: {e}")
        return {}