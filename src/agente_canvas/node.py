# src/agente_canvas/node.py
import json
import sys
from pathlib import Path
from typing import Any, Dict

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from src.agente_canvas.service import CanvasService
from src.state import CanvasCourse, GlauxState


def canvas_agent_node(state: GlauxState) -> Dict[str, Any]:
    print(
        "\n [Agente Canvas] Conectando à API do Canvas e buscando cursos/arquivos..."
    )

    try:
        service = CanvasService(api_key=state.canvas_api_key)

        # 1. Busca cursos válidos da API
        courses = service.get_user_courses()

        if not courses:
            raise Exception(
                "Nenhum curso retornado (API instável ou offline)."
            )

        print(
            f" [Agente Canvas] {len(courses)} disciplinas válidas encontradas na API."
        )

        all_downloaded_files = []
        for course in courses:
            print(
                f" [Agente Canvas] Ingerindo dados da matéria [{course.name}]..."
            )
            files = service.fetch_and_save_course_data(course.id)
            all_downloaded_files.extend(files)

        return {
            "courses": [c.model_dump() for c in courses],
            "downloaded_files": all_downloaded_files,
        }

    except Exception as e:
        print(f" [Agente Canvas] Instabilidade na API ({e}).")
        print(
            " [Agente Canvas] Ativando Modo Offline: Carregando dados locais de data/raw/..."
        )

        # MODO OFFLINE: Lê as pastas já baixadas em data/raw para não travar o desenvolvimento
        raw_dir = Path("data/raw")
        local_courses = []

        if raw_dir.exists():
            # Mapeamento manual dos IDs de cursos locais conhecidos
            course_map = {
                96829: "ESTUDOS DE BANCO DE DADOS I - PRÁTICA",
                96825: "ALGORITMOS E LINGUAGEM DE PROGRAMAÇÃO - PRÁTICA",
                96834: "ESTUDOS DE BANCO DE DADOS I",
                96856: "FUNDAMENTOS DE ENGENHARIA DE SISTEMAS",
                96839: "INTRODUÇÃO ÀS TECNOLOGIAS PARA WEB",
                96848: "MÉTODOS DE ENGENHARIA DE SOFTWARE",
                96844: "PROJETO INTEGRADOR II - ENGENHARIA DE SOFTWARE",
            }

            for folder in raw_dir.iterdir():
                if folder.is_dir() and folder.name.isdigit():
                    c_id = int(folder.name)
                    c_name = course_map.get(
                        c_id, f"Disciplina (ID {c_id})"
                    )
                    local_courses.append(
                        CanvasCourse(id=c_id, name=c_name)
                    )

        print(
            f" [Modo Offline] {len(local_courses)} matérias locais recuperadas de data/raw/."
        )

        return {
            "courses": [c.model_dump() for c in local_courses],
            "downloaded_files": [],
        }