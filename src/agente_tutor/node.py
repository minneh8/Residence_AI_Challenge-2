# src/agente_tutor/node.py
import sys
from pathlib import Path
from typing import Any, Dict, List

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from src.state import CanvasCourse, GlauxState
from src.agente_tutor.service import TutorService

COURSE_MAP_LOCAL = {
    96829: "ESTUDOS DE BANCO DE DADOS I - PRATICA",
    96825: "ALGORITMOS E LINGUAGEM DE PROGRAMACAO - PRATICA",
    96834: "ESTUDOS DE BANCO DE DADOS I",
    96856: "FUNDAMENTOS DE ENGENHARIA DE SISTEMAS",
    96839: "INTRODUCAO AS TECNOLOGIAS PARA WEB",
    96848: "METODOS DE ENGENHARIA DE SOFTWARE",
    96844: "PROJETO INTEGRADOR II - ENGENHARIA DE SOFTWARE",
}


def _carregar_cursos_fallback(curso_alvo: int | None) -> List[CanvasCourse]:
    """Carrega disciplinas de data/raw/ quando o Canvas foi pulado pelo Orquestrador."""
    raw_dir = Path("data/raw")
    cursos: List[CanvasCourse] = []
    if not raw_dir.exists():
        return cursos

    for folder in raw_dir.iterdir():
        if folder.is_dir() and folder.name.isdigit():
            c_id = int(folder.name)
            if curso_alvo is not None and c_id != curso_alvo:
                continue
            cursos.append(
                CanvasCourse(id=c_id, name=COURSE_MAP_LOCAL.get(c_id, f"Disciplina (ID {c_id})"))
            )
    return cursos


def tutor_agent_node(state: GlauxState) -> Dict[str, Any]:
    print("\n[Agente Tutor] Iniciando processamento pedagogico...")

    try:
        service = TutorService()
        courses = [CanvasCourse(**c) if isinstance(c, dict) else c for c in state.courses]

        # Se o Canvas foi pulado pelo Orquestrador, carrega os cursos locais
        if not courses:
            courses = _carregar_cursos_fallback(state.curso_alvo)

        if state.curso_alvo is not None:
            courses = [c for c in courses if c.id == state.curso_alvo]

        # 1. Gera Cronograma
        schedule = service.generate_schedule(courses)
        print(f"[Agente Tutor] Cronograma com {len(schedule)} entrega(s) futura(s) mapeada(s).")

        # 2. Gera Resumos (pula se o botao clicado foi apenas GERAR_CRONOGRAMA)
        summaries = list(state.summaries)
        if state.action != "GERAR_CRONOGRAMA":
            summaries = []
            for course in courses:
                summary = service.generate_summary_for_course(course.id, course.name)
                summaries.append(summary.model_dump())
            print(f"[Agente Tutor] {len(summaries)} resumo(s) gerado(s).")
        else:
            print("[Agente Tutor] Acao='GERAR_CRONOGRAMA'; geracao de resumos pulada.")

        return {
            "courses": [c.model_dump() for c in courses],
            "assignments": [s.model_dump() for s in schedule],
            "summaries": summaries,
        }
    except Exception as e:
        print(f"[Agente Tutor] Erro durante a execucao: {e}")
        return {}