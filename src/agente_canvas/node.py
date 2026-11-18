# src/agente_canvas/node.py
import sys
from pathlib import Path
from typing import Any, Dict, List

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from src.agente_canvas.classificador import classificar
from src.agente_canvas.service import (
    CATEGORIAS_LISTAS,
    CanvasAuthError,
    CanvasService,
    _contar_paginas_pdf,
    _nome_seguro,
)
from src.rag.indexacao import indexar_curso
from src.state import CanvasCourse, GlauxState

COURSE_MAP_OFFLINE = {
    96829: "ESTUDOS DE BANCO DE DADOS I - PRATICA",
    96825: "ALGORITMOS E LINGUAGEM DE PROGRAMACAO - PRATICA",
    96834: "ESTUDOS DE BANCO DE DADOS I",
    96856: "FUNDAMENTOS DE ENGENHARIA DE SISTEMAS",
    96839: "INTRODUCAO AS TECNOLOGIAS PARA WEB",
    96848: "METODOS DE ENGENHARIA DE SOFTWARE",
    96844: "PROJETO INTEGRADOR II - ENGENHARIA DE SOFTWARE",
}


def _organizar_pasta_local_offline(course_folder: Path) -> None:
    """Organiza PDFs soltos na raiz de data/raw/<course_id>/ sem precisar de token do Canvas."""
    import shutil

    pasta_conteudo = course_folder / "conteudo"
    pasta_listas = course_folder / "listas"
    pasta_conteudo.mkdir(parents=True, exist_ok=True)
    pasta_listas.mkdir(parents=True, exist_ok=True)

    pdfs_soltos = [
        f for f in course_folder.iterdir()
        if f.is_file() and f.suffix.lower() == ".pdf"
    ]
    for pdf in pdfs_soltos:
        nome_limpo = _nome_seguro(pdf.name)
        categoria, origem = classificar(
            nome=nome_limpo,
            tamanho=pdf.stat().st_size,
            paginas=_contar_paginas_pdf(pdf),
        )
        subpasta = pasta_listas if categoria in CATEGORIAS_LISTAS else pasta_conteudo
        destino = subpasta / nome_limpo
        if pdf.resolve() != destino.resolve():
            shutil.move(str(pdf), str(destino))
        print(
            f" [Modo Offline] PDF organizado [{categoria} | {origem}]: "
            f"{course_folder.name}/{subpasta.name}/{nome_limpo}"
        )


def _indexar_curso_seguro(course_id: int) -> None:
    """Indexa o curso (ou pula se nada mudou), isolando qualquer erro do RAG."""
    try:
        r = indexar_curso(course_id)
        if r.get("pulado"):
            print(
                f" [RAG] Curso {course_id} ja indexado em {r['colecao']} "
                f"({r['chunks']} chunks); reindexacao pulada."
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
    """Carrega cursos locais de data/raw/ quando o Canvas esta indisponivel."""
    print(" [Agente Canvas] Ativando Modo Offline: lendo data/raw/...")
    raw_dir = Path("data/raw")
    local_courses: List[CanvasCourse] = []

    if raw_dir.exists():
        for folder in raw_dir.iterdir():
            if folder.is_dir() and folder.name.isdigit():
                c_id = int(folder.name)
                if state.curso_alvo and c_id != state.curso_alvo:
                    continue
                _organizar_pasta_local_offline(folder)
                c_name = COURSE_MAP_OFFLINE.get(c_id, f"Disciplina (ID {c_id})")
                local_courses.append(CanvasCourse(id=c_id, name=c_name))

    print(f" [Modo Offline] {len(local_courses)} materia(s) local(is) recuperada(s).")
    for course in local_courses:
        _indexar_curso_seguro(course.id)

    return {
        "courses": [c.model_dump() for c in local_courses],
        "downloaded_files": [],
    }


def canvas_agent_node(state: GlauxState) -> Dict[str, Any]:
    print("\n [Agente Canvas] Conectando a API do Canvas e buscando cursos/arquivos...")

    try:
        service = CanvasService(api_key=state.canvas_api_key)
        courses = service.get_user_courses()
    except CanvasAuthError:
        raise
    except Exception as e:
        print(f" [Agente Canvas] Canvas indisponivel ({e}).")
        return _modo_offline(state)

    if state.curso_alvo:
        courses = [c for c in courses if c.id == state.curso_alvo]
        if not courses:
            print(
                f" [Agente Canvas] Curso {state.curso_alvo} nao esta entre os "
                "cursos ativos na API; tentando modo offline."
            )
            return _modo_offline(state)

    print(f" [Agente Canvas] {len(courses)} disciplina(s) valida(s) encontrada(s).")

    all_downloaded_files: List[str] = []
    for course in courses:
        print(f" [Agente Canvas] Ingerindo dados da materia [{course.name}]...")
        resultado = service.fetch_and_save_course_data(course.id)
        all_downloaded_files.extend(resultado["baixados"])
        print(
            f" [Agente Canvas] Curso {course.id}: "
            f"{len(resultado['baixados'])} PDF(s) baixado(s), "
            f"{len(resultado['pulados'])} pulado(s)."
        )
        _indexar_curso_seguro(course.id)

    return {
        "courses": [c.model_dump() for c in courses],
        "downloaded_files": all_downloaded_files,
    }