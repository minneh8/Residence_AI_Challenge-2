# src/agente_canvas/node.py
import sys
from pathlib import Path
from typing import Any, Dict, List

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from src.agente_canvas.service import CanvasAuthError, CanvasConfigError, CanvasService
from src.rag.indexacao import curso_indexado, indexar_curso
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


def _imprimir_resumo(r: Dict[str, Any]) -> None:
    """Resumo da sincronização de um curso."""
    print(
        f" [Agente Canvas] Curso {r['course_id']}: "
        f"{len(r['novos'])} novo(s), {len(r['atualizados'])} atualizado(s), "
        f"{len(r['recuperados'])} recuperado(s), {len(r['registrados'])} só registrado(s), "
        f"{len(r['migrados'])} migrado(s), {len(r['pulados'])} pulado(s) (não PDF), "
        f"{len(r['falhas'])} falha(s); {r['requisicoes']} requisição(ões) ao Canvas."
    )
    if r.get("parou_em"):
        print(f"   parada antecipada em: {r['parou_em']}")
    if r.get("pendentes_llm"):
        print(f"   aguardando a LLM (erro da API, fora do catálogo): {r['pendentes_llm']}")
    if r.get("removidos"):
        print(f"   removidos do catálogo (não existem mais no Canvas): {r['removidos']}")
    print(f"   por categoria (catálogo): {r['categorias']}")
    motivo = "não (houve falha ou LLM indisponível)"
    print(f"   estado do aluno gravado: {'sim' if r['estado_gravado'] else motivo}")


def _modo_offline(state: GlauxState) -> Dict[str, Any]:
    """Carrega cursos locais de data/raw/ quando o Canvas está indisponível.

    Não move nem reclassifica arquivos: só usa o que já está no disco.
    """
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
        # Token ausente/inválido ou CANVAS_API_URL faltando: o grafo encerra com código 1.
        raise
    except Exception as e:
        # CanvasUnavailableError (503/rede) ou qualquer outra falha: modo offline.
        print(f" [Agente Canvas] Canvas indisponível ({e}).")
        return _modo_offline(state)

    # --curso <id>: sincroniza, indexa e resume só esse curso.
    if state.curso_alvo:
        courses = [c for c in courses if c.id == state.curso_alvo]
        if not courses:
            print(
                f" [Agente Canvas] Curso {state.curso_alvo} não está entre os "
                "cursos ativos na API; tentando modo offline."
            )
            return _modo_offline(state)

    print(f" [Agente Canvas] {len(courses)} disciplina(s) válida(s) encontrada(s).")
    if state.sync_completo:
        print(" [Agente Canvas] --completo: percorrendo todos os arquivos de cada curso.")

    all_downloaded_files: List[str] = []
    for course in courses:
        print(f" [Agente Canvas] Sincronizando a matéria [{course.name}]...")
        try:
            resultado = service.sincronizar_curso(course.id, completo=state.sync_completo)
        except CanvasConfigError:
            raise
        except CanvasAuthError:
            # 401 num curso (ex.: aba de arquivos bloqueada): avisa e segue.
            print(f" [Agente Canvas] Aviso: sem permissão no curso {course.id} (401); "
                  "pulando para o próximo.")
            continue
        except Exception as e:
            print(f" [Agente Canvas] Aviso: falha ao sincronizar o curso {course.id} ({e}); "
                  "pulando para o próximo.")
            continue

        _imprimir_resumo(resultado)
        all_downloaded_files.extend(resultado["baixados"])

        # Indexa só se algo mudou (ou se o curso ainda não está no índice).
        if resultado["mudou"]:
            _indexar_curso_seguro(course.id)
        elif not curso_indexado(course.id):
            print(f" [RAG] Curso {course.id} sem mudanças, mas fora do índice; indexando.")
            _indexar_curso_seguro(course.id)
        else:
            print(f" [RAG] Curso {course.id}: nada mudou no Canvas; reindexação pulada.")

    return {
        "user_id": service.user_id or state.user_id,
        "courses": [c.model_dump() for c in courses],
        "downloaded_files": all_downloaded_files,
    }
