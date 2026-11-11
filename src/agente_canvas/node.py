# src/agente_canvas/node.py
import sys
from pathlib import Path
from typing import Any, Dict, List

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from src.agente_canvas.service import CanvasAuthError, CanvasService
from src.rag.indexacao import indexar_curso
from src.state import CanvasCourse, GlauxState

# Nomes conhecidos de cursos locais, usados só no modo offline.
COURSE_MAP_OFFLINE = {
    96829: "ESTUDOS DE BANCO DE DADOS I - PRÁTICA",
    96825: "ALGORITMOS E LINGUAGEM DE PROGRAMAÇÃO - PRÁTICA",
    96834: "ESTUDOS DE BANCO DE DADOS I",
    96856: "FUNDAMENTOS DE ENGENHARIA DE SISTEMAS",
    96839: "INTRODUÇÃO ÀS TECNOLOGIAS PARA WEB",
    96848: "MÉTODOS DE ENGENHARIA DE SOFTWARE",
    96844: "PROJETO INTEGRADOR II - ENGENHARIA DE SOFTWARE",
}


def _indexar_curso_seguro(course_id: int) -> None:
    """Indexa o curso (ou pula se nada mudou), isolando qualquer erro do RAG."""
    try:
        r = indexar_curso(course_id)
        if r.get("pulado"):
            print(
                f" [RAG] Curso {course_id} já indexado em {r['colecao']} "
                f"({r['chunks']} chunks); reindexação pulada."
            )
        elif r.get("aviso"):
            print(f" [RAG] Curso {course_id}: {r['aviso']}")
        else:
            print(
                f" [RAG] Curso {course_id} indexado em {r['colecao']}: "
                f"{r['chunks']} chunks ({r['tempo_s']}s)."
            )
    except Exception as e:
        print(f" [RAG] Falha ao indexar o curso {course_id}: {e}")


def _modo_offline(state: GlauxState) -> Dict[str, Any]:
    """Carrega cursos locais de data/raw/ quando o Canvas está indisponível."""
    print(" [Agente Canvas] Ativando Modo Offline: lendo data/raw/...")
    raw_dir = Path("data/raw")
    local_courses: List[CanvasCourse] = []

    if raw_dir.exists():
        for folder in raw_dir.iterdir():
            if folder.is_dir() and folder.name.isdigit():
                c_id = int(folder.name)
                if state.curso_alvo and c_id != state.curso_alvo:
                    continue
                c_name = COURSE_MAP_OFFLINE.get(c_id, f"Disciplina (ID {c_id})")
                local_courses.append(CanvasCourse(id=c_id, name=c_name))

    print(f" [Modo Offline] {len(local_courses)} matéria(s) local(is) recuperada(s).")
    for course in local_courses:
        _indexar_curso_seguro(course.id)

    return {
        "courses": [c.model_dump() for c in local_courses],
        "downloaded_files": [],
    }


def canvas_agent_node(state: GlauxState) -> Dict[str, Any]:
    print("\n [Agente Canvas] Conectando à API do Canvas e buscando cursos/arquivos...")

    try:
        service = CanvasService(api_key=state.canvas_api_key)
        courses = service.get_user_courses()
    except CanvasAuthError:
        # Token ausente/inválido: propaga para o grafo encerrar com código 1.
        raise
    except Exception as e:
        # CanvasUnavailableError (503/rede) ou qualquer outra falha: modo offline.
        print(f" [Agente Canvas] Canvas indisponível ({e}).")
        return _modo_offline(state)

    # --curso <id>: restringe toda a esteira a um único curso.
    if state.curso_alvo:
        courses = [c for c in courses if c.id == state.curso_alvo]
        if not courses:
            print(
                f" [Agente Canvas] Curso {state.curso_alvo} não está entre os "
                "cursos ativos na API; tentando modo offline."
            )
            return _modo_offline(state)

    print(f" [Agente Canvas] {len(courses)} disciplina(s) válida(s) encontrada(s).")

    all_downloaded_files: List[str] = []
    for course in courses:
        print(f" [Agente Canvas] Ingerindo dados da matéria [{course.name}]...")
        resultado = service.fetch_and_save_course_data(course.id)
        all_downloaded_files.extend(resultado["baixados"])
        print(
            f" [Agente Canvas] Curso {course.id}: "
            f"{len(resultado['baixados'])} PDF(s) baixado(s), "
            f"{len(resultado['pulados'])} pulado(s)."
        )
        # Indexa o curso recém-baixado, isolando falhas do RAG.
        _indexar_curso_seguro(course.id)

    return {
        "courses": [c.model_dump() for c in courses],
        "downloaded_files": all_downloaded_files,
    }
