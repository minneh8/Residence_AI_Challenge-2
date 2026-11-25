"""Interface web do Glaux (Streamlit).

Rodar a partir da raiz do projeto:

    .\\.venv\\Scripts\\streamlit.exe run app/streamlit_app.py

A interface só conhece src/interface/acoes.py; os agentes (Canvas, Tutor,
Gerador) e o RAG ficam atrás dessa camada.
"""

import sys
from pathlib import Path

import streamlit as st

# Permite importar o pacote src/ ao rodar via streamlit a partir da raiz.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agente_canvas.service import CanvasAuthError, CanvasUnavailableError  # noqa: E402
from src.interface import acoes  # noqa: E402

st.set_page_config(page_title="Glaux", page_icon="🦉", layout="wide")

NOMES_AGENTES = {"canvas": "Canvas", "tutor": "Tutor", "gerador": "Gerador"}


# --------------------------------------------------------------------------
# Modelo de embeddings: uma carga por processo, reaproveitada entre reruns
# --------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def carregar_modelo_embeddings():
    """Carrega o modelo E5 uma única vez (compartilhado entre as sessões)."""
    from src.rag.embeddings import carregar_modelo

    return carregar_modelo()


def garantir_modelo() -> None:
    """Garante o modelo carregado antes de qualquer busca no RAG."""
    with st.spinner("Carregando o modelo de embeddings (só na primeira vez)..."):
        carregar_modelo_embeddings()


def mensagem_erro(e: Exception) -> str:
    """Transforma exceções em mensagens amigáveis (sem stack trace)."""
    if isinstance(e, CanvasAuthError):  # inclui CanvasConfigError
        return str(e)
    if isinstance(e, CanvasUnavailableError):
        return acoes.MSG_ERRO_CANVAS_OFF
    return f"Não foi possível concluir: {e}"


def rodape_execucao(resultado: dict) -> None:
    """Rodapé com os agentes executados e o tempo de cada um."""
    partes = [
        f"{NOMES_AGENTES.get(a, a)} ({resultado['tempos'].get(a, 0):.1f}s)"
        for a in resultado["agentes"]
    ]
    if partes:
        st.caption(
            "Agentes executados: " + " → ".join(partes)
            + f" · total {resultado['tempo_total']:.1f}s"
        )


# --------------------------------------------------------------------------
# Barra lateral: usuário, curso e sincronização
# --------------------------------------------------------------------------
def barra_lateral() -> tuple[int | None, str | None]:
    st.sidebar.title("🦉 Glaux")

    # Usuário autenticado (nome vindo do Canvas; o token nunca aparece).
    if "nome_usuario" not in st.session_state:
        try:
            st.session_state.nome_usuario = acoes.autenticar()
        except Exception as e:
            st.session_state.nome_usuario = None
            st.session_state.erro_auth = mensagem_erro(e)
    if st.session_state.get("nome_usuario"):
        st.sidebar.success(f"Autenticado: {st.session_state.nome_usuario}")
    else:
        st.sidebar.error(st.session_state.get("erro_auth", "Não autenticado no Canvas."))

    st.sidebar.divider()

    # Seleção do curso: pastas em data/raw + opção de listar do Canvas.
    if st.sidebar.button("Listar cursos do Canvas"):
        try:
            st.session_state.cursos_canvas = acoes.listar_cursos_canvas()
        except Exception as e:
            st.sidebar.error(mensagem_erro(e))

    nomes_canvas = {c["id"]: c["name"] for c in st.session_state.get("cursos_canvas", [])}
    ids = sorted(set(acoes.cursos_locais()) | set(nomes_canvas))

    if not ids:
        st.sidebar.info("Nenhum curso local. Use 'Listar cursos do Canvas' e sincronize.")
        return None, None

    def rotulo(cid: int) -> str:
        nome = nomes_canvas.get(cid)
        return f"{cid} — {nome}" if nome else f"{cid} — (disciplina local)"

    curso_id = st.sidebar.selectbox("Curso", ids, format_func=rotulo)
    curso_nome = nomes_canvas.get(curso_id)

    st.sidebar.divider()

    # Sincronização.
    forcar = st.sidebar.checkbox(
        "Forçar varredura completa",
        help="Percorre todos os arquivos do Canvas, sem a parada antecipada.",
    )
    if st.sidebar.button("Sincronizar Canvas", type="primary"):
        with st.spinner("Sincronizando com o Canvas..."):
            st.session_state.ultima_sync = acoes.executar_acao(
                "SINCRONIZAR_CANVAS", curso_id, forcar=forcar, course_name=curso_nome
            )

    return curso_id, curso_nome


# --------------------------------------------------------------------------
# Resultado da sincronização
# --------------------------------------------------------------------------
def mostrar_sincronizacao() -> None:
    res = st.session_state.get("ultima_sync")
    if not res:
        return
    st.subheader("Resultado da sincronização")
    if res["erro"]:
        st.error(res["erro"])
        rodape_execucao(res)
        return

    resumos = (res["resultados"].get("canvas") or {}).get("resumos", [])
    for r in resumos:
        st.markdown(f"**{r['curso']}** (curso {r['course_id']})")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Novos", r["novos"])
        c2.metric("Atualizados", r["atualizados"])
        c3.metric("Migrados", r["migrados"])
        c4.metric("Pulados", r["pulados"])
        c5.metric("Pendentes LLM", r["pendentes_llm"])
        col_a, col_b = st.columns(2)
        col_a.write(f"Requisições ao Canvas: **{r['requisicoes']}**")
        tempo = res.get("tempo_sincronizacao")
        col_b.write(f"Tempo da sincronização: **{tempo:.1f}s**" if tempo is not None else "")
        if r["categorias"]:
            st.write("Por categoria: " + ", ".join(
                f"{cat}: {qtd}" for cat, qtd in r["categorias"].items()))
        if r.get("parou_em"):
            st.caption(f"Parada antecipada em: {r['parou_em']}")
    rodape_execucao(res)
    st.divider()


# --------------------------------------------------------------------------
# Abas
# --------------------------------------------------------------------------
def aba_materiais(curso_id: int) -> None:
    materiais = acoes.carregar_materiais(curso_id)
    if not materiais:
        st.info("Nenhum material catalogado. Sincronize o Canvas primeiro.")
        return
    for categoria, arquivos in materiais.items():
        st.subheader(f"{categoria} ({len(arquivos)})")
        st.table([
            {
                "Arquivo": a["nome"],
                "Páginas": a["paginas"] if a["paginas"] is not None else "—",
                "Classificação": a["classificado_por"],
                "Origem": a["origem"],
            }
            for a in arquivos
        ])


def aba_resumo(curso_id: int, curso_nome: str | None) -> None:
    tema = st.text_input("Tema do resumo", key="tema_resumo",
                         placeholder="ex.: hipótese nula")
    if st.button("Gerar resumo", key="btn_resumo"):
        if not tema.strip():
            st.warning("Escreva um tema para gerar o resumo.")
            return
        garantir_modelo()
        with st.spinner("O Tutor está gerando o resumo..."):
            res = acoes.executar_acao("GERAR_RESUMO", curso_id, tema=tema,
                                      course_name=curso_nome)
        if res["erro"]:
            st.error(res["erro"])
        else:
            summaries = (res["resultados"].get("tutor") or {}).get("summaries", [])
            if not summaries:
                st.warning("O Tutor não retornou resumo. Verifique o índice do curso.")
            for s in summaries:
                st.markdown(f"### {s.get('topic_title', '')}")
                st.markdown(s.get("summary_text", ""))
                fontes = s.get("sources_used", [])
                if fontes:
                    st.markdown("**Fontes:**")
                    for f in fontes:
                        st.markdown(
                            f"- `{f['arquivo']}`, p.{f['pagina']}-{f['pagina_fim']}")
        rodape_execucao(res)


def aba_questoes(curso_id: int, curso_nome: str | None) -> None:
    tema = st.text_input("Tema das questões", key="tema_quest",
                         placeholder="ex.: hipótese nula")
    quantidade = st.number_input("Quantidade", min_value=1, max_value=10, value=3, step=1)
    if st.button("Gerar questões", key="btn_quest"):
        if not tema.strip():
            st.warning("Escreva um tema para gerar as questões.")
            return
        garantir_modelo()
        with st.spinner("O Gerador está montando as questões..."):
            res = acoes.executar_acao("GERAR_QUESTOES", curso_id, tema=tema,
                                      quantidade=int(quantidade), course_name=curso_nome)
        if res["erro"]:
            st.error(res["erro"])
        else:
            gerador = res["resultados"].get("gerador") or {}
            if gerador.get("status") != "ok":
                st.warning(gerador.get("mensagem") or "Não foi possível gerar as questões.")
            for i, q in enumerate(gerador.get("questoes", []), start=1):
                st.markdown(f"**Questão {i} ({q.get('assunto', '')})**")
                st.markdown(q.get("enunciado", ""))
                if q.get("tipo") == "multipla_escolha":
                    for letra, texto in q.get("alternativas", {}).items():
                        st.markdown(f"- **{letra})** {texto}")
                    st.caption(f"Resposta correta: {q.get('correta')}")
                ref = q.get("trecho_referencia", {})
                if ref:
                    st.caption(
                        f"Fonte: {ref.get('arquivo')}, "
                        f"p.{ref.get('pagina')}-{ref.get('pagina_fim')}")
                st.divider()
        rodape_execucao(res)


def aba_prazos(curso_id: int) -> None:
    prazos = acoes.carregar_prazos(curso_id)
    if not prazos:
        st.info("Nenhuma tarefa em assignments.json. Sincronize o Canvas primeiro.")
        return
    proximos = [p for p in prazos if p["proximo"]]
    if proximos:
        st.success(f"{len(proximos)} tarefa(s) nos próximos 7 dias.")
    for p in prazos:
        dias = p["days_remaining"]
        if p["proximo"]:
            rotulo_dias = f"⚠️ faltam {dias} dia(s)"
        elif dias is None:
            rotulo_dias = "sem data"
        elif dias < 0:
            rotulo_dias = f"vencida há {abs(dias)} dia(s)"
        else:
            rotulo_dias = f"faltam {dias} dia(s)"
        entregue = " · entregue" if p["submitted"] else ""
        data = p["due_at"] or "—"
        linha = f"**{p['nome']}** — {data} ({rotulo_dias}{entregue})"
        if p["proximo"]:
            st.warning(linha)
        else:
            st.markdown(linha)


# --------------------------------------------------------------------------
# Página
# --------------------------------------------------------------------------
def main() -> None:
    curso_id, curso_nome = barra_lateral()
    st.title("Glaux — assistente de estudos")

    if curso_id is None:
        st.info("Selecione um curso na barra lateral para começar.")
        return

    mostrar_sincronizacao()

    aba_mat, aba_res, aba_quest, aba_praz = st.tabs(
        ["Materiais", "Resumo", "Questões", "Prazos"])
    with aba_mat:
        aba_materiais(curso_id)
    with aba_res:
        aba_resumo(curso_id, curso_nome)
    with aba_quest:
        aba_questoes(curso_id, curso_nome)
    with aba_praz:
        aba_prazos(curso_id)


if __name__ == "__main__":
    main()
