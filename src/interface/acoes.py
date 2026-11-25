"""Ações da interface Streamlit do Glaux.

`executar_acao()` monta o GlauxState e roda os agentes na ordem definida pela
ação, medindo o tempo de cada etapa e devolvendo um dicionário com o resultado
de cada agente, a ordem em que rodaram e os tempos.

Hoje esta função decide ela mesma a rota (quais agentes rodam), porque o nó do
orquestrador ainda NÃO está no graph.py: o grafo atual só tem as arestas fixas
canvas -> tutor -> gerador e descarta o resumo da sincronização. Quando o nó do
orquestrador entrar no graph.py, `executar_acao` passa a só definir `state.action`
e chamar o grafo (`build_glaux_graph().invoke(state)`); a rota e os passos
passam a ser decididos lá dentro, pelo OrchestratorService.

Os valores de ACOES são exatamente os de `state.action` do agente orquestrador
(origin/orquestrador, 5b517bf): SINCRONIZAR_CANVAS, GERAR_CRONOGRAMA,
GERAR_RESUMO, GERAR_QUESTOES e FLUXO_COMPLETO. A lógica de planejamento abaixo
segue a mesma ideia do OrchestratorService (pular o Canvas quando já há dados
locais, salvo --forçar), com uma diferença documentada em `planejar()`.
"""

import hashlib
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv

from src.agente_canvas.catalogo import ler_json, para_datetime
from src.agente_canvas.service import (
    CanvasAuthError,
    CanvasConfigError,
    CanvasService,
    CanvasUnavailableError,
)
from src.state import CanvasCourse, GlauxState

# Arquivos locais da interface (fora do Git, dentro de data/).
CAMINHO_CACHE_RESUMOS = Path("data/processed/resumos_cache.json")
CAMINHO_NOMES_CURSOS = Path("data/processed/cursos_nomes.json")

# Teto de trechos usados no resumo de um arquivo (busca no Chroma por curso+arquivo).
MAX_TRECHOS_ARQUIVO = 12

# Valores de ação aceitos (iguais ao Literal de state.action do orquestrador).
ACOES = (
    "SINCRONIZAR_CANVAS",
    "GERAR_CRONOGRAMA",
    "GERAR_RESUMO",
    "GERAR_QUESTOES",
    "FLUXO_COMPLETO",
)

# Mensagens amigáveis (sem stack trace) para os erros mais comuns.
MSG_ERRO_GROQ = (
    "O serviço de IA (Groq) está indisponível no momento. "
    "Verifique a GROQ_API_KEY no .env ou tente de novo em alguns minutos."
)
MSG_ERRO_CANVAS_OFF = (
    "O Canvas está indisponível no momento (rede ou servidor fora do ar). "
    "Tente sincronizar de novo mais tarde."
)
MSG_ERRO_SEM_INDICE = (
    "Esta disciplina ainda não foi indexada no RAG. "
    "Sincronize o Canvas para baixar e indexar o material primeiro."
)
MSG_ERRO_GENERICO = "Não foi possível concluir a ação: {detalhe}"


# --------------------------------------------------------------------------
# Planejamento: qual agente roda em cada ação
# --------------------------------------------------------------------------
def planejar(
    action: str,
    *,
    forcar: bool = False,
    tem_pdfs: bool = False,
    tem_dados: bool = False,
    com_questoes: bool = False,
) -> List[str]:
    """Lista ordenada de agentes ("canvas", "tutor", "gerador") para a ação.

    Segue a lógica do OrchestratorService: pula o Canvas quando já há dados
    locais, a menos que `forcar` (equivale a --completo / force_sync). A única
    diferença é em GERAR_QUESTOES: o Gerador lê o RAG diretamente e NÃO depende
    do resumo do Tutor, então aqui o Tutor fica de fora (o orquestrador o inclui
    para "preparar contexto", o que no nosso Gerador seria uma chamada de LLM a
    mais sem efeito sobre as questões).
    """
    if action == "SINCRONIZAR_CANVAS":
        return ["canvas"]
    if action == "GERAR_CRONOGRAMA":
        return ["canvas", "tutor"] if forcar or not tem_dados else ["tutor"]
    if action == "GERAR_RESUMO":
        return ["canvas", "tutor"] if forcar or not tem_pdfs else ["tutor"]
    if action == "GERAR_QUESTOES":
        return ["canvas", "gerador"] if forcar or not tem_pdfs else ["gerador"]
    if action == "FLUXO_COMPLETO":
        passos = ["canvas", "tutor"]
        if com_questoes:
            passos.append("gerador")
        return passos
    raise ValueError(f"Ação desconhecida: {action!r}. Use uma de {list(ACOES)}.")


# --------------------------------------------------------------------------
# Agentes reais (cada um recebe o state e devolve {"updates", "resultado"})
# --------------------------------------------------------------------------
def _agente_canvas(state: GlauxState) -> Dict[str, Any]:
    """Sincroniza o(s) curso(s) e indexa o que mudou; devolve o resumo por curso.

    Usa o CanvasService diretamente (e não o canvas_agent_node) porque o nó
    imprime o resumo da sincronização e o descarta: a interface precisa dos
    números (novos, atualizados, migrados, pendentes da LLM, etc.).
    """
    from src.rag.indexacao import curso_indexado, indexar_curso

    service = CanvasService(api_key=state.canvas_api_key)
    courses = service.get_user_courses()
    if state.curso_alvo:
        courses = [c for c in courses if c.id == state.curso_alvo]

    resumos: List[Dict[str, Any]] = []
    baixados: List[str] = []
    for course in courses:
        r = service.sincronizar_curso(course.id, completo=state.sync_completo)
        baixados.extend(r.get("baixados", []))
        reindexou = False
        if r.get("mudou") or not curso_indexado(course.id):
            try:
                indexar_curso(course.id)
                reindexou = True
            except Exception as e:  # o RAG não derruba a sincronização
                print(f" [Interface] Falha ao indexar o curso {course.id}: {e}")
        # Guarda o nome da matéria localmente: o seletor da barra lateral passa a
        # mostrá-lo sem bater na API do Canvas nos reruns seguintes.
        registrar_nomes_cursos({course.id: course.name})
        resumo = _resumo_para_interface(course, r)
        resumo["reindexou"] = reindexou
        resumo["chunks"] = contar_chunks(course.id)
        resumos.append(resumo)

    updates = {
        "user_id": service.user_id or state.user_id,
        "courses": [c.model_dump() for c in courses],
        "downloaded_files": baixados,
    }
    return {"updates": updates, "resultado": {"resumos": resumos}}


def _resumo_para_interface(course: CanvasCourse, r: Dict[str, Any]) -> Dict[str, Any]:
    """Converte o resumo de sincronizar_curso em dados prontos para a tela.

    Além das contagens, traz as listas de PDFs com nome e categoria (novos,
    atualizados, bloqueados e pendentes da LLM) para os avisos da barra lateral.
    """
    categoria = _categoria_por_nome(course.id)

    def itens(nomes: List[str], estado: str) -> List[Dict[str, Any]]:
        return [{"nome": n, "categoria": categoria.get(n, "—"), "estado": estado}
                for n in nomes]

    return {
        "course_id": course.id,
        "curso": course.name,
        "novos": len(r.get("novos", [])),
        "atualizados": len(r.get("atualizados", [])),
        "recuperados": len(r.get("recuperados", [])),
        "migrados": len(r.get("migrados", [])),
        "registrados": len(r.get("registrados", [])),
        "pulados": len(r.get("pulados", [])),
        "falhas": len(r.get("falhas", [])),
        "pendentes_llm": len(r.get("pendentes_llm", [])),
        "categorias": r.get("categorias", {}),
        "requisicoes": r.get("requisicoes", 0),
        "parou_em": r.get("parou_em"),
        # Listas detalhadas (nome + categoria + como entrou).
        "novos_itens": (itens(r.get("novos", []), "novo")
                        + itens(r.get("recuperados", []), "recuperado")),
        "atualizados_itens": (itens(r.get("atualizados", []), "atualizado")
                              + itens(r.get("migrados", []), "migrado")),
        "bloqueados_nomes": list(r.get("bloqueados", [])),
        "pendentes_llm_nomes": list(r.get("pendentes_llm", [])),
    }


def _categoria_por_nome(course_id: int, raw_dir: str = "data/raw") -> Dict[str, str]:
    """Mapa nome do PDF -> categoria, lido do _arquivos.json do curso."""
    catalogo = ler_json(Path(raw_dir) / str(course_id) / "_arquivos.json", {})
    return {e.get("nome"): e.get("categoria", "outros") for e in catalogo.values()}


def _agente_tutor(state: GlauxState) -> Dict[str, Any]:
    """Gera cronograma e resumos com o TutorService.

    Chama o serviço diretamente (em vez de tutor_agent_node) para que uma falha
    do Groq suba como exceção e vire uma mensagem amigável; o nó engole todos os
    erros e devolve {} silenciosamente.
    """
    from src.agente_tutor.service import TutorService

    service = TutorService()
    courses = [CanvasCourse(**c) if isinstance(c, dict) else c for c in state.courses]
    if state.curso_alvo:
        courses = [c for c in courses if c.id == state.curso_alvo]

    schedule = service.generate_schedule(courses)
    tarefas_por_curso: Dict[int, list] = defaultdict(list)
    for tarefa in schedule:
        tarefas_por_curso[tarefa.course_id].append(tarefa)

    summaries = []
    for course in courses:
        resumo = service.generate_summary_for_course(
            course.id, course.name,
            tarefas=tarefas_por_curso.get(course.id, []),
            tema=state.tema,
        )
        summaries.append(resumo.model_dump())

    updates = {
        "assignments": [s.model_dump() for s in schedule],
        "summaries": summaries,
    }
    return {"updates": updates, "resultado": {"summaries": summaries,
                                              "assignments": updates["assignments"]}}


def _agente_gerador(state: GlauxState) -> Dict[str, Any]:
    """Gera as questões pelo gerador_questoes_node (já devolve status amigável)."""
    from src.agente_gerador.node import gerador_questoes_node

    updates = gerador_questoes_node(state)
    return {
        "updates": updates,
        "resultado": {
            "questoes": updates.get("generated_questions", []),
            "status": updates.get("generation_status"),
            "mensagem": updates.get("generation_message"),
        },
    }


AGENTES_PADRAO: Dict[str, Callable[[GlauxState], Dict[str, Any]]] = {
    "canvas": _agente_canvas,
    "tutor": _agente_tutor,
    "gerador": _agente_gerador,
}


# --------------------------------------------------------------------------
# Ponto de entrada da interface
# --------------------------------------------------------------------------
def executar_acao(
    action: str,
    course_id: Optional[int],
    tema: Optional[str] = None,
    quantidade: Optional[int] = None,
    forcar: bool = False,
    *,
    course_name: Optional[str] = None,
    raw_dir: str = "data/raw",
    agentes: Optional[Dict[str, Callable[[GlauxState], Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Executa a ação montando o estado e rodando os agentes na ordem do plano.

    Args:
        action: uma das ACOES (os mesmos valores de state.action do orquestrador).
        course_id: disciplina alvo. None roda em todos os cursos (FLUXO_COMPLETO).
        tema: tema do resumo/das questões (Tutor e Gerador).
        quantidade: número de questões (Gerador).
        forcar: varredura completa do Canvas (--completo / force_sync).
        course_name: nome do curso, usado quando o Canvas não roda (dados locais),
            para o Tutor ter o nome da disciplina sem bater na API.
        raw_dir: raiz dos dados locais (injetável nos testes).
        agentes: mapa nome->callable para substituir os agentes reais (testes).

    Returns:
        Dicionário com: action, agentes (ordem), tempos (por agente),
        tempo_total, tempo_sincronizacao (tempo só do Canvas, ou None),
        resultados (por agente) e erro (mensagem amigável ou None).
    """
    if action not in ACOES:
        raise ValueError(f"Ação desconhecida: {action!r}. Use uma de {list(ACOES)}.")
    agentes = agentes or AGENTES_PADRAO
    load_dotenv()

    state = GlauxState(
        user_id="estudante_glaux",
        canvas_api_key=os.getenv("CANVAS_API_KEY"),
        tema=tema,
        curso_alvo=course_id,
        sync_completo=forcar,
        quantidade_questoes=quantidade,
    )

    plano = planejar(
        action,
        forcar=forcar,
        tem_pdfs=_tem_pdfs(course_id, raw_dir),
        tem_dados=_tem_dados(course_id, raw_dir),
        com_questoes=quantidade is not None,
    )

    # Quando o Canvas não roda, o Tutor ainda precisa de state.courses: monta a
    # disciplina a partir do que já se sabe (id e nome), sem bater na API.
    if "canvas" not in plano and course_id is not None:
        state.courses = [CanvasCourse(id=course_id,
                                      name=course_name or f"Disciplina (ID {course_id})")]

    resultados: Dict[str, Any] = {}
    tempos: Dict[str, float] = {}
    ordem: List[str] = []
    erro: Optional[str] = None

    inicio_total = time.perf_counter()
    try:
        for nome in plano:
            t0 = time.perf_counter()
            saida = agentes[nome](state)
            tempos[nome] = time.perf_counter() - t0
            ordem.append(nome)
            _aplicar_updates(state, saida.get("updates", {}))
            resultados[nome] = saida.get("resultado")
    except CanvasConfigError as e:
        erro = str(e)  # CanvasConfigError é subclasse de CanvasAuthError: vem antes
    except CanvasAuthError as e:
        erro = str(e)  # mensagem já amigável (token ausente/inválido)
    except CanvasUnavailableError:
        erro = MSG_ERRO_CANVAS_OFF
    except Exception as e:  # inclui falhas do Groq (groq.GroqError)
        if _eh_erro_groq(e):
            erro = MSG_ERRO_GROQ
        else:
            erro = MSG_ERRO_GENERICO.format(detalhe=e)

    return {
        "action": action,
        "agentes": ordem,
        "tempos": tempos,
        "tempo_total": time.perf_counter() - inicio_total,
        "tempo_sincronizacao": tempos.get("canvas"),
        "resultados": resultados,
        "erro": erro,
    }


def _aplicar_updates(state: GlauxState, updates: Dict[str, Any]) -> None:
    """Aplica os campos devolvidos por um agente ao estado (como o LangGraph faria)."""
    for chave, valor in updates.items():
        if hasattr(state, chave):
            setattr(state, chave, valor)


def _tem_pdfs(course_id: Optional[int], raw_dir: str) -> bool:
    """True se há ao menos um PDF em data/raw/<course_id>/ (em qualquer subpasta)."""
    if course_id is None:
        return False
    pasta = Path(raw_dir) / str(course_id)
    return pasta.is_dir() and any(pasta.rglob("*.pdf"))


def _tem_dados(course_id: Optional[int], raw_dir: str) -> bool:
    """True se há PDFs ou assignments.json em data/raw/<course_id>/."""
    if course_id is None:
        return False
    pasta = Path(raw_dir) / str(course_id)
    return _tem_pdfs(course_id, raw_dir) or (pasta / "assignments.json").exists()


def _eh_erro_groq(e: Exception) -> bool:
    """True se a exceção veio do SDK da Groq (sem importar groq se não precisar)."""
    try:
        import groq
    except Exception:
        return False
    return isinstance(e, groq.GroqError)


# --------------------------------------------------------------------------
# Leitura dos dados locais (sem rede): usados pela barra lateral e pelas abas
# --------------------------------------------------------------------------
def autenticar(api_key: Optional[str] = None, api_url: Optional[str] = None) -> str:
    """Valida o token e devolve o nome do usuário autenticado no Canvas."""
    load_dotenv()
    service = CanvasService(api_key=api_key, api_url=api_url)
    usuario = service.validar_token()
    return getattr(usuario, "name", "usuário")


def listar_cursos_canvas() -> List[Dict[str, Any]]:
    """Cursos ativos do usuário no Canvas: lista de {"id", "name"}.

    Guarda os nomes em data/processed/ para o seletor exibi-los nos próximos
    reruns sem bater na API de novo.
    """
    load_dotenv()
    service = CanvasService()
    cursos = [{"id": c.id, "name": c.name} for c in service.get_user_courses()]
    registrar_nomes_cursos({c["id"]: c["name"] for c in cursos})
    return cursos


# --------------------------------------------------------------------------
# Mensagens de erro amigáveis (reusadas pela tela e pelos resumos)
# --------------------------------------------------------------------------
def erro_amigavel(e: Exception) -> str:
    """Transforma exceções em mensagens claras, sem stack trace."""
    if isinstance(e, CanvasConfigError):  # subclasse de CanvasAuthError: vem antes
        return str(e)
    if isinstance(e, CanvasAuthError):
        return str(e)
    if isinstance(e, CanvasUnavailableError):
        return MSG_ERRO_CANVAS_OFF
    if _eh_erro_groq(e):
        return MSG_ERRO_GROQ
    return MSG_ERRO_GENERICO.format(detalhe=e)


# --------------------------------------------------------------------------
# Arquivos JSON locais da interface (nomes de cursos e cache de resumos)
# --------------------------------------------------------------------------
def _salvar_json(caminho: Path, dados: Any) -> None:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def nomes_cursos(caminho: Path = CAMINHO_NOMES_CURSOS) -> Dict[int, str]:
    """Nomes de matéria conhecidos localmente: {course_id: nome}."""
    return {int(k): v for k, v in ler_json(Path(caminho), {}).items()}


def registrar_nomes_cursos(mapa: Dict[int, str],
                           caminho: Path = CAMINHO_NOMES_CURSOS) -> None:
    """Mescla e grava nomes de matéria descobertos (listar cursos ou sincronizar)."""
    novos = {str(cid): nome for cid, nome in (mapa or {}).items() if nome}
    if not novos:
        return
    atual = ler_json(Path(caminho), {})
    atual.update(novos)
    _salvar_json(Path(caminho), atual)


# --------------------------------------------------------------------------
# Estatísticas do curso (sem LLM): PDFs por categoria e total de chunks
# --------------------------------------------------------------------------
def contar_chunks(course_id: int) -> Optional[int]:
    """Nº de chunks do curso na coleção padrão do RAG (None se o Chroma falhar)."""
    try:
        from src.rag.busca import COLECAO_PADRAO
        from src.rag.indexacao import obter_colecao

        col = obter_colecao(COLECAO_PADRAO)
        if col is None:
            return 0
        return len(col.get(where={"course_id": course_id}, include=[])["ids"])
    except Exception:
        return None


def resumo_estatisticas(course_id: int, raw_dir: str = "data/raw") -> Dict[str, Any]:
    """Resumo fixo do topo: PDFs por categoria, total de PDFs e total de chunks."""
    materiais = carregar_materiais(course_id, raw_dir)
    por_categoria = {cat: len(arqs) for cat, arqs in materiais.items()}
    return {
        "por_categoria": por_categoria,
        "total_pdfs": sum(por_categoria.values()),
        "total_chunks": contar_chunks(course_id),
    }


# --------------------------------------------------------------------------
# Recuperação de trechos de UM arquivo (Chroma por curso + arquivo; sem LLM)
# --------------------------------------------------------------------------
def trechos_do_arquivo(course_id: int, arquivo: str,
                       max_trechos: int = MAX_TRECHOS_ARQUIVO) -> List[Dict[str, Any]]:
    """Trechos de um PDF específico, ordenados por página e limitados a max_trechos.

    Busca no Chroma só por metadata (curso + arquivo), sem embeddings nem LLM. Se
    houver mais trechos que o teto, amostra de forma espaçada para cobrir o PDF
    inteiro (e manter o conjunto determinístico, bom para a chave do cache).
    """
    from src.rag.busca import COLECAO_PADRAO
    from src.rag.indexacao import obter_colecao

    col = obter_colecao(COLECAO_PADRAO)
    if col is None:
        return []
    r = col.get(
        where={"$and": [{"course_id": course_id}, {"arquivo": arquivo}]},
        include=["documents", "metadatas"],
    )
    itens = [
        {"texto": texto, "arquivo": meta["arquivo"], "pagina": meta["pagina"],
         "pagina_fim": meta["pagina_fim"], "score": None}
        for texto, meta in zip(r.get("documents") or [], r.get("metadatas") or [])
    ]
    itens.sort(key=lambda t: (t["pagina"], t["pagina_fim"]))
    return _amostrar(itens, max_trechos)


def _amostrar(itens: List[Any], maximo: int) -> List[Any]:
    """Amostra espaçada e determinística de até `maximo` itens, preservando a ordem."""
    if maximo <= 0 or len(itens) <= maximo:
        return itens
    passo = len(itens) / maximo
    indices = sorted({min(len(itens) - 1, int(i * passo)) for i in range(maximo)})
    return [itens[i] for i in indices]


# --------------------------------------------------------------------------
# Cache de resumos: data/processed/resumos_cache.json
# Chave = (curso, tipo, alvo, ids dos chunks usados). Muda o material -> nova chave.
# --------------------------------------------------------------------------
def _ids_trechos(trechos: List[Dict[str, Any]]) -> List[str]:
    """Identidade estável de cada trecho: 'arquivo:pagina-pagina_fim' (ordenada)."""
    return sorted(f"{t['arquivo']}:{t['pagina']}-{t['pagina_fim']}" for t in trechos)


def _chave_cache(course_id: int, tipo: str, alvo: str, ids: List[str]) -> str:
    """Chave do cache: curso|tipo|alvo|hash(ids dos chunks)."""
    digest = hashlib.sha1("\n".join(ids).encode("utf-8")).hexdigest()[:16]
    return f"{course_id}|{tipo}|{alvo}|{digest}"


def _tutor_padrao():
    """Instancia o TutorService real (import tardio: evita puxar o Groq sem uso)."""
    from src.agente_tutor.service import TutorService

    return TutorService()


def _eh_recusa(texto: Optional[str]) -> bool:
    try:
        from src.agente_tutor.service import MSG_RECUSA
    except Exception:
        return False
    return (texto or "").strip() == MSG_RECUSA


def _resultado_erro(msg: str, t0: float, em_cache: bool = False) -> Dict[str, Any]:
    return {
        "ok": False, "erro": msg, "recusa": False,
        "topic_title": None, "summary_text": None, "sources_used": [],
        "em_cache": em_cache,
        "detalhes": {"trechos": [], "modelo": None, "tokens": None,
                     "chamadas_llm": 0, "em_cache": em_cache,
                     "tempo": time.perf_counter() - t0},
    }


def _resultado_do_cache(entrada: Dict[str, Any], t0: float) -> Dict[str, Any]:
    texto = entrada.get("summary_text")
    return {
        "ok": True, "erro": None, "recusa": _eh_recusa(texto),
        "topic_title": entrada.get("topic_title"),
        "summary_text": texto,
        "sources_used": entrada.get("sources_used", []),
        "em_cache": True,
        "detalhes": {"trechos": entrada.get("trechos", []),
                     "modelo": entrada.get("modelo"), "tokens": entrada.get("tokens"),
                     "chamadas_llm": 0, "em_cache": True,
                     "gerado_em": entrada.get("gerado_em"),
                     "tempo": time.perf_counter() - t0},
    }


def _resumir_com_cache(course_id: int, tipo: str, alvo: str,
                       trechos: List[Dict[str, Any]], course_name: str, *,
                       foco: str, topic_title: str, forcar: bool,
                       tutor, cache_path: Path, t0: float) -> Dict[str, Any]:
    """Núcleo compartilhado: checa o cache e, só no clique sem cache, chama o LLM."""
    ids = _ids_trechos(trechos)
    chave = _chave_cache(course_id, tipo, alvo, ids)
    cache = ler_json(Path(cache_path), {})
    if not forcar and chave in cache:
        return _resultado_do_cache(cache[chave], t0)

    tutor = tutor or _tutor_padrao()
    try:
        resumo, det = tutor.resumir_trechos(
            course_id, course_name, trechos, foco=foco, topic_title=topic_title)
    except Exception as e:
        return _resultado_erro(erro_amigavel(e), t0)

    trechos_resumo = [
        {"arquivo": t["arquivo"], "pagina": t["pagina"],
         "pagina_fim": t["pagina_fim"], "score": t.get("score")}
        for t in trechos
    ]
    entrada = {
        "topic_title": resumo.topic_title,
        "summary_text": resumo.summary_text,
        "sources_used": resumo.sources_used,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "modelo": det.get("modelo"),
        "tokens": det.get("tokens"),
        "trechos": trechos_resumo,
        "ids": ids,
    }
    cache[chave] = entrada
    _salvar_json(Path(cache_path), cache)

    return {
        "ok": True, "erro": None, "recusa": _eh_recusa(resumo.summary_text),
        "topic_title": resumo.topic_title,
        "summary_text": resumo.summary_text,
        "sources_used": resumo.sources_used,
        "em_cache": False,
        "detalhes": {"trechos": trechos_resumo, "modelo": det.get("modelo"),
                     "tokens": det.get("tokens"),
                     "chamadas_llm": det.get("chamadas_llm", 0),
                     "em_cache": False, "tempo": time.perf_counter() - t0},
    }


def resumir_arquivo(course_id: int, arquivo: str, course_name: Optional[str] = None, *,
                    forcar: bool = False, tutor=None, trechos_fn=None,
                    cache_path: Path = CAMINHO_CACHE_RESUMOS,
                    max_trechos: int = MAX_TRECHOS_ARQUIVO) -> Dict[str, Any]:
    """Resume UMA aula com os trechos daquele PDF (curso + arquivo). Usa o cache.

    Só chama o LLM quando não há resumo salvo para o mesmo conjunto de trechos
    (ou com forcar=True, o "Gerar de novo"). A recuperação dos trechos não usa LLM.
    """
    t0 = time.perf_counter()
    trechos_fn = trechos_fn or trechos_do_arquivo
    trechos = trechos_fn(course_id, arquivo, max_trechos)
    if not trechos:
        return _resultado_erro(
            f"O arquivo '{arquivo}' não tem trechos indexados no RAG. "
            "Sincronize o Canvas para (re)indexar o material.", t0)
    return _resumir_com_cache(
        course_id, "arquivo", arquivo, trechos,
        course_name or f"Disciplina (ID {course_id})",
        foco=f"Aula: {arquivo}", topic_title=f"Resumo de {arquivo}",
        forcar=forcar, tutor=tutor, cache_path=cache_path, t0=t0)


def resumir_tema(course_id: int, tema: str, course_name: Optional[str] = None, *,
                 forcar: bool = False, tutor=None, buscar_fn=None,
                 cache_path: Path = CAMINHO_CACHE_RESUMOS) -> Dict[str, Any]:
    """Resume um tema com o Tutor (busca nos slides). Usa o cache; só chama o LLM no clique."""
    t0 = time.perf_counter()
    tema = (tema or "").strip()
    if not tema:
        return _resultado_erro("Escreva um tema para gerar o resumo.", t0)
    tutor = tutor or _tutor_padrao()
    trechos = buscar_fn(course_id, tema) if buscar_fn else tutor.buscar_tema(course_id, tema)
    if not trechos:
        return _resultado_erro(MSG_ERRO_SEM_INDICE, t0)
    return _resumir_com_cache(
        course_id, "tema", tema, trechos,
        course_name or f"Disciplina (ID {course_id})",
        foco=tema, topic_title=f"Tema: {tema}",
        forcar=forcar, tutor=tutor, cache_path=cache_path, t0=t0)


def resumir_tarefa(course_id: int, titulo: str, descricao: Optional[str] = None,
                   course_name: Optional[str] = None, *, forcar: bool = False,
                   tutor=None, buscar_fn=None,
                   cache_path: Path = CAMINHO_CACHE_RESUMOS) -> Dict[str, Any]:
    """Resume o conteúdo de uma tarefa (consulta = título + descrição). Usa o cache."""
    t0 = time.perf_counter()
    titulo = (titulo or "").strip()
    if not titulo:
        return _resultado_erro("A tarefa não tem título para montar a consulta.", t0)
    tutor = tutor or _tutor_padrao()
    trechos = (buscar_fn(course_id, titulo, descricao) if buscar_fn
               else tutor.buscar_tarefa(course_id, titulo, descricao))
    if not trechos:
        return _resultado_erro(MSG_ERRO_SEM_INDICE, t0)
    return _resumir_com_cache(
        course_id, "tarefa", titulo, trechos,
        course_name or f"Disciplina (ID {course_id})",
        foco=titulo, topic_title=f"Tarefa: {titulo}",
        forcar=forcar, tutor=tutor, cache_path=cache_path, t0=t0)


def ultima_sincronizacao(course_id: int,
                         state_dir: str = "data/canvas_state") -> Optional[str]:
    """Instante (ISO) da última sincronização do curso, lido do canvas_state.

    O estado fica em data/canvas_state/<user_id>.json; varre os arquivos e pega o
    sincronizado_em mais recente para o curso. None se nunca sincronizou.
    """
    pasta = Path(state_dir)
    if not pasta.exists():
        return None
    melhor: Optional[str] = None
    for arq in pasta.glob("*.json"):
        info = (ler_json(arq, {}) or {}).get(str(course_id)) or {}
        quando = info.get("sincronizado_em")
        if quando and (melhor is None or quando > melhor):
            melhor = quando
    return melhor


def cursos_locais(raw_dir: str = "data/raw") -> List[int]:
    """Ids dos cursos que já têm pasta em data/raw/."""
    pasta = Path(raw_dir)
    if not pasta.exists():
        return []
    return sorted(
        int(f.name) for f in pasta.iterdir() if f.is_dir() and f.name.isdigit()
    )


def carregar_materiais(course_id: int, raw_dir: str = "data/raw") -> Dict[str, List[Dict[str, Any]]]:
    """Arquivos do _arquivos.json agrupados por categoria.

    Cada item traz nome, páginas, origem (regra que decidiu) e classificado_por
    ("regra" ou "LLM"). As categorias saem ordenadas e os arquivos por nome.
    """
    catalogo = ler_json(Path(raw_dir) / str(course_id) / "_arquivos.json", {})
    grupos: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entrada in catalogo.values():
        origem = str(entrada.get("origem") or "")
        grupos[entrada.get("categoria", "outros")].append({
            "nome": entrada.get("nome"),
            "paginas": entrada.get("paginas"),
            "origem": origem,
            "classificado_por": "LLM" if origem.startswith("llm") else "regra",
        })
    for arquivos in grupos.values():
        arquivos.sort(key=lambda a: (a["nome"] or "").lower())
    return dict(sorted(grupos.items()))


def carregar_prazos(course_id: int, raw_dir: str = "data/raw",
                    janela_dias: int = 7) -> List[Dict[str, Any]]:
    """Tarefas do assignments.json ordenadas por data (sem data no fim).

    Cada item traz nome, due_at, submitted, days_remaining e proximo (True se
    faltam de 0 a `janela_dias` dias). days_remaining é None quando não há data.
    """
    from datetime import datetime, timezone

    dados = ler_json(Path(raw_dir) / str(course_id) / "assignments.json", [])
    agora = datetime.now(timezone.utc)
    prazos: List[Dict[str, Any]] = []
    for tarefa in dados:
        due = para_datetime(tarefa.get("due_at"))
        dias = (due - agora).days if due else None
        prazos.append({
            "nome": tarefa.get("name") or tarefa.get("title") or "Tarefa sem título",
            "descricao": tarefa.get("description") or "",
            "due_at": tarefa.get("due_at"),
            "submitted": bool(tarefa.get("submitted", False)),
            "days_remaining": dias,
            "proximo": dias is not None and 0 <= dias <= janela_dias,
        })
    prazos.sort(key=lambda p: (p["due_at"] is None, p["due_at"] or ""))
    return prazos
