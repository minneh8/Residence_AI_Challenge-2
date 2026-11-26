"""Interface web do Glaux (Streamlit).

Rodar a partir da raiz do projeto:

    .\\.venv\\Scripts\\streamlit.exe run app/streamlit_app.py

Esta camada só DESENHA a tela: a lógica (sincronização, resumos, cache,
estatísticas) vive em src/interface/acoes.py e a formatação em
src/interface/formatacao.py. O front final reaproveita as duas.

Regra de ouro: a LLM (Groq) só é chamada dentro do clique de um botão. Abrir a
página, trocar de aba ou de curso e qualquer rerun NÃO chamam a LLM. Os
resultados ficam em st.session_state; o modelo de embeddings carrega sob demanda.
"""

import sys
from pathlib import Path

import streamlit as st

# Permite importar o pacote src/ ao rodar via streamlit a partir da raiz.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.interface import acoes  # noqa: E402
from src.interface import formatacao as fmt  # noqa: E402

st.set_page_config(page_title="Glaux", page_icon="🦉", layout="wide")

# Único bloco de CSS: só ajusta espaçamento e arredonda os cartões.
st.markdown(
    """
    <style>
      .block-container {padding-top: 2.4rem; padding-bottom: 3rem; max-width: 1200px;}
      [data-testid="stVerticalBlockBorderWrapper"] {border-radius: 12px;}
      [data-testid="stMetricValue"] {font-size: 1.35rem;}
      h2, h3 {margin-top: .4rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

ORDEM_CATEGORIAS = ["slides", "listas", "trabalho", "livros", "outros"]
LABEL_CATEGORIA = {"slides": "Slides", "listas": "Listas", "trabalho": "Trabalho",
                   "livros": "Livros", "outros": "Outros"}
COR_STATUS = {"entregue": "green", "pendente": "orange", "atrasada": "red"}
COR_ESTADO = {"novo": "blue", "recuperado": "gray", "atualizado": "orange",
              "migrado": "gray"}
TITULO_SECAO = {"atrasadas": "Atrasadas", "hoje": "Hoje",
                "proximos": "Próximos 7 dias", "adiante": "Mais adiante"}


# --------------------------------------------------------------------------
# Infraestrutura leve (modelo, session_state, selos)
# --------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def carregar_modelo_embeddings():
    from src.rag.embeddings import carregar_modelo

    return carregar_modelo()


def garantir_modelo() -> None:
    """Carrega o modelo E5 (só antes de uma busca semântica: tema/tarefa)."""
    with st.spinner("Carregando o modelo de embeddings (só na primeira vez)..."):
        carregar_modelo_embeddings()


def estado(chave: str) -> dict:
    if chave not in st.session_state:
        st.session_state[chave] = {}
    return st.session_state[chave]


def selo(texto: str, cor: str) -> str:
    """Markdown de um selo colorido nativo do Streamlit."""
    return f":{cor}-badge[{texto}]"


# --------------------------------------------------------------------------
# Render compartilhado de resumos (aula / tema / tarefa)
# --------------------------------------------------------------------------
def render_detalhes_resumo(det: dict) -> None:
    with st.expander("Detalhes técnicos", expanded=False):
        origem = ("cache (nenhuma chamada à LLM)" if det.get("em_cache")
                  else f"{det.get('chamadas_llm', 0)} chamada(s) à LLM")
        st.write(f"**Origem:** {origem} · **tempo:** {det.get('tempo', 0):.1f}s")
        if det.get("gerado_em"):
            st.write(f"**Gerado em:** {fmt.data_hora(det['gerado_em'])}")
        if det.get("modelo"):
            st.write(f"**Agente:** Tutor · **modelo:** {det['modelo']}")
        tokens = det.get("tokens")
        if tokens:
            st.write(f"**Tokens:** entrada {fmt.numero_br(tokens.get('entrada'))} · "
                     f"saída {fmt.numero_br(tokens.get('saida'))} · "
                     f"total {fmt.numero_br(tokens.get('total'))}")
        trechos = det.get("trechos") or []
        if trechos:
            st.write(f"**Trechos usados ({len(trechos)}):**")
            st.table([
                {"Arquivo": t["arquivo"],
                 "Páginas": f"{t['pagina']}-{t['pagina_fim']}",
                 "Score": f"{t['score']:.3f}" if t.get("score") is not None else "—"}
                for t in trechos
            ])


def render_resultado_resumo(res: dict) -> None:
    with st.container(border=True):
        if res.get("erro"):
            st.error(res["erro"])
            render_detalhes_resumo(res.get("detalhes", {}))
            return

        cab = st.columns([5, 1])
        if res.get("topic_title"):
            cab[0].markdown(f"#### {res['topic_title']}")
        if res.get("em_cache"):
            cab[1].markdown(selo("resumo salvo", "green"))

        if res.get("recusa"):
            st.warning(res["summary_text"])
        else:
            st.markdown(res.get("summary_text", ""))

        fontes = res.get("sources_used") or []
        if fontes:
            st.caption("Fontes: " + "  ·  ".join(
                f"{f['arquivo']} p.{f['pagina']}-{f['pagina_fim']}" for f in fontes))

        render_detalhes_resumo(res.get("detalhes", {}))


# --------------------------------------------------------------------------
# Barra lateral
# --------------------------------------------------------------------------
def barra_lateral() -> tuple[int | None, str | None]:
    st.sidebar.title("🦉 Glaux")

    if "nome_usuario" not in st.session_state:
        try:
            st.session_state.nome_usuario = acoes.autenticar()
        except Exception as e:
            st.session_state.nome_usuario = None
            st.session_state.erro_auth = acoes.erro_amigavel(e)
    if st.session_state.get("nome_usuario"):
        st.sidebar.success(f"Autenticado: {st.session_state.nome_usuario}")
    else:
        st.sidebar.error(st.session_state.get("erro_auth", "Não autenticado no Canvas."))

    st.sidebar.divider()

    nomes = acoes.nomes_cursos()
    ids = acoes.cursos_locais()
    if not ids:
        if st.sidebar.button("Buscar matérias no Canvas"):
            _sincronizar(None, None, todas=True)
        st.sidebar.info("Nenhuma matéria local ainda. Sincronize o Canvas.")
        return None, None

    def rotulo(cid: int) -> str:
        nome = nomes.get(cid)
        return fmt.nome_materia(nome) if nome else f"Curso {cid}"

    curso_id = st.sidebar.selectbox("Matéria", ids, format_func=rotulo)
    curso_nome = nomes.get(curso_id)

    st.sidebar.divider()
    todas = st.sidebar.checkbox("Todas as matérias",
                                help="Sincroniza todos os cursos, não só o selecionado.")
    forcar = st.sidebar.checkbox("Forçar varredura completa",
                                 help="Percorre todos os arquivos, sem parada antecipada.")
    if st.sidebar.button("Sincronizar", type="primary", use_container_width=True):
        _sincronizar(None if todas else curso_id, curso_nome, todas=todas, forcar=forcar)

    quando = acoes.ultima_sincronizacao(curso_id)
    st.sidebar.caption(
        f"Última sincronização: {fmt.ha_quanto_tempo(quando)}" if quando
        else "Ainda não sincronizado nesta matéria.")

    return curso_id, curso_nome


def _sincronizar(curso_id, curso_nome, *, todas=False, forcar=False) -> None:
    with st.spinner("Sincronizando com o Canvas..."):
        res = acoes.executar_acao("SINCRONIZAR_CANVAS", curso_id,
                                  forcar=forcar, course_name=curso_nome)
    st.session_state.ultima_sync = res
    if res["erro"]:
        st.toast(res["erro"], icon="⚠️")
        return
    resumos = (res["resultados"].get("canvas") or {}).get("resumos", [])
    total_novos = sum(len(r.get("novos_itens", [])) + len(r.get("atualizados_itens", []))
                      for r in resumos)
    if total_novos:
        st.toast(f"{fmt.plural(total_novos, 'material novo', 'materiais novos')} "
                 "sincronizado(s).", icon="✅")
    else:
        st.toast("Tudo em dia — nenhum material novo.", icon="✅")


# --------------------------------------------------------------------------
# Cartão de resultado da sincronização (na página)
# --------------------------------------------------------------------------
def cartao_sincronizacao() -> None:
    res = st.session_state.get("ultima_sync")
    if not res:
        return
    if res["erro"]:
        with st.container(border=True):
            st.error(res["erro"])
        return

    tempo = res.get("tempo_sincronizacao")
    tempo_txt = f"{tempo:.1f}".replace(".", ",") + " s" if tempo is not None else "—"
    for r in (res["resultados"].get("canvas") or {}).get("resumos", []):
        novos = r.get("novos_itens", []) + r.get("atualizados_itens", [])
        bloqueados = r.get("bloqueados_nomes", [])
        pendentes = r.get("pendentes_llm_nomes", [])

        with st.container(border=True):
            if novos:
                st.markdown(f"**Material novo em {fmt.nome_materia(r['curso'])}**")
                for it in novos:
                    cor = COR_ESTADO.get(it["estado"], "gray")
                    st.markdown(
                        f"{selo(it['estado'], cor)} **{fmt.nome_arquivo(it['nome'])}** "
                        f"· {it['categoria']}")
            else:
                st.markdown(f"✅ **Tudo em dia** — nenhum material novo ({tempo_txt}).")

            if bloqueados or pendentes:
                avisos = []
                if bloqueados:
                    avisos.append("Bloqueados para o aluno: " + ", ".join(bloqueados))
                if pendentes:
                    avisos.append("Classificação pendente da LLM: " + ", ".join(pendentes))
                st.warning("  \n".join(avisos))

            with st.expander("Detalhes técnicos", expanded=False):
                st.write(f"**Requisições ao Canvas:** {fmt.numero_br(r.get('requisicoes', 0))}")
                st.write(f"**Tempo só do Canvas:** {tempo_txt}")
                st.write(f"**Reindexou o RAG:** {'sim' if r.get('reindexou') else 'não'}")
                st.write(f"**Chunks do curso:** {fmt.numero_br(r.get('chunks'))}")
                if r.get("parou_em"):
                    st.write(f"**Listagem parou em:** {r['parou_em']}")


# --------------------------------------------------------------------------
# Cabeçalho: nome da matéria + métricas
# --------------------------------------------------------------------------
def cabecalho(curso_id: int, curso_nome: str | None) -> None:
    st.header(fmt.nome_materia(curso_nome) if curso_nome else f"Curso {curso_id}")
    stats = acoes.resumo_estatisticas(curso_id)
    por_cat = stats["por_categoria"]
    quando = acoes.ultima_sincronizacao(curso_id)

    c = st.columns(5)
    c[0].metric("PDFs", fmt.numero_br(stats["total_pdfs"]))
    c[1].metric("Slides", fmt.numero_br(por_cat.get("slides", 0)))
    c[2].metric("Listas", fmt.numero_br(por_cat.get("listas", 0)))
    c[3].metric("Chunks", fmt.numero_br(stats["total_chunks"]))
    c[4].metric("Sincronizado", fmt.ha_quanto_tempo(quando) if quando else "nunca")


# --------------------------------------------------------------------------
# Aba Materiais
# --------------------------------------------------------------------------
def aba_materiais(curso_id: int, curso_nome: str | None) -> None:
    materiais = acoes.carregar_materiais(curso_id)
    if not materiais:
        st.info("Nenhum material catalogado. Sincronize o Canvas primeiro.")
        return

    cache = estado("resumos_arquivo")
    categorias = [c for c in ORDEM_CATEGORIAS if c in materiais]
    categorias += [c for c in materiais if c not in ORDEM_CATEGORIAS]

    for categoria in categorias:
        arquivos = materiais[categoria]
        st.subheader(f"{LABEL_CATEGORIA.get(categoria, categoria.title())} ({len(arquivos)})")
        colunas = st.columns(3)
        for i, a in enumerate(arquivos):
            nome = a["nome"]
            with colunas[i % 3].container(border=True):
                st.markdown(f"**{fmt.nome_arquivo(nome)}**")
                paginas = a["paginas"]
                selo_cls = (selo("IA", "violet") if a["classificado_por"] == "LLM"
                            else selo("regra", "gray"))
                pag_txt = f"{fmt.plural(paginas, 'página')}" if paginas else "—"
                st.caption(f"{pag_txt} · {selo_cls}")
                if categoria == "slides":
                    if st.button("Resumir esta aula", key=f"mat_{curso_id}_{nome}",
                                 use_container_width=True):
                        with st.spinner(f"Resumindo {fmt.nome_arquivo(nome)}..."):
                            cache[(curso_id, nome)] = acoes.resumir_arquivo(
                                curso_id, nome, curso_nome)
                        st.session_state.aula_sel = (curso_id, nome)

    sel = st.session_state.get("aula_sel")
    if sel and sel[0] == curso_id and sel in cache:
        st.divider()
        st.subheader(f"Resumo — {fmt.nome_arquivo(sel[1])}")
        render_resultado_resumo(cache[sel])
        if st.button("Gerar de novo", key=f"regen_{sel[1]}"):
            with st.spinner("Gerando um novo resumo..."):
                cache[sel] = acoes.resumir_arquivo(curso_id, sel[1], curso_nome, forcar=True)
            st.rerun()


# --------------------------------------------------------------------------
# Aba Resumo por tema
# --------------------------------------------------------------------------
def aba_resumo(curso_id: int, curso_nome: str | None) -> None:
    cache = estado("resumos_tema")
    col = st.columns([4, 1])
    tema = col[0].text_input("Tema do resumo", key="tema_resumo",
                             placeholder="ex.: hipótese nula", label_visibility="collapsed")
    if col[1].button("Resumir", type="primary", use_container_width=True):
        if not tema.strip():
            st.warning("Escreva um tema para gerar o resumo.")
        else:
            garantir_modelo()
            with st.spinner("O Tutor está gerando o resumo..."):
                cache[(curso_id, tema.strip())] = acoes.resumir_tema(curso_id, tema, curso_nome)

    chave = (curso_id, tema.strip())
    if tema.strip() and chave in cache:
        render_resultado_resumo(cache[chave])


# --------------------------------------------------------------------------
# Aba Prazos
# --------------------------------------------------------------------------
def _cartao_tarefa(curso_id, curso_nome, p, cache) -> None:
    status = fmt.status_prazo(p["due_at"], p["submitted"])
    with st.container(border=True):
        linha = st.columns([5, 2])
        linha[0].markdown(f"**{fmt.titulo_tarefa(p['nome'])}**")
        linha[1].markdown(selo(status.capitalize(), COR_STATUS[status]))
        st.caption(fmt.data_relativa(p["due_at"], submitted=p["submitted"]))

        if not p["submitted"]:
            nome = p["nome"]
            chave = (curso_id, nome)
            if st.button("Resumir o conteúdo desta tarefa", key=f"tar_{curso_id}_{nome}"):
                garantir_modelo()
                with st.spinner("O Tutor está resumindo o conteúdo da tarefa..."):
                    cache[chave] = acoes.resumir_tarefa(
                        curso_id, nome, p.get("descricao"), curso_nome)
            if chave in cache:
                render_resultado_resumo(cache[chave])


def aba_prazos(curso_id: int, curso_nome: str | None) -> None:
    prazos = acoes.carregar_prazos(curso_id)
    if not prazos:
        st.info("Nenhuma tarefa em assignments.json. Sincronize o Canvas primeiro.")
        return

    cache = estado("resumos_tarefa")
    secoes = {k: [] for k in ("atrasadas", "hoje", "proximos", "adiante", "entregues")}
    for p in prazos:
        secoes[fmt.secao_prazo(p["due_at"], p["submitted"])].append(p)

    for chave in ("atrasadas", "hoje", "proximos", "adiante"):
        tarefas = secoes[chave]
        if not tarefas:
            continue
        st.subheader(f"{TITULO_SECAO[chave]} ({len(tarefas)})")
        for p in tarefas:
            _cartao_tarefa(curso_id, curso_nome, p, cache)

    entregues = secoes["entregues"]
    if entregues:
        with st.expander(f"Entregues ({len(entregues)})", expanded=False):
            for p in entregues:
                _cartao_tarefa(curso_id, curso_nome, p, cache)


# --------------------------------------------------------------------------
# Aba Questões
# --------------------------------------------------------------------------
# Campos opcionais que o gerador pode devolver (usa o primeiro que existir).
CAMPOS_GABARITO = ("resposta_esperada", "resposta_modelo", "gabarito",
                   "resposta_correta", "resposta")
CAMPOS_EXPLICACAO = ("explicacao", "justificativa", "comentario")


def _primeiro_campo(q: dict, chaves: tuple[str, ...]):
    for k in chaves:
        v = q.get(k)
        if v:
            return v
    return None


def aba_questoes(curso_id: int, curso_nome: str | None) -> None:
    cache = estado("questoes")
    col = st.columns([3, 1, 1])
    tema = col[0].text_input("Tema das questões", key="tema_quest",
                             placeholder="ex.: hipótese nula", label_visibility="collapsed")
    quantidade = col[1].number_input("Qtd.", min_value=1, max_value=10, value=3, step=1,
                                     label_visibility="collapsed")
    if col[2].button("Gerar", type="primary", use_container_width=True):
        if not tema.strip():
            st.warning("Escreva um tema para gerar as questões.")
        else:
            garantir_modelo()
            with st.spinner("O Gerador está montando as questões..."):
                res = acoes.executar_acao(
                    "GERAR_QUESTOES", curso_id, tema=tema,
                    quantidade=int(quantidade), course_name=curso_nome)
            # Cada geração ganha um id novo: ele entra nas chaves dos widgets,
            # então respostas marcadas/reveladas da rodada anterior não vazam.
            st.session_state.geracao_questoes = st.session_state.get("geracao_questoes", 0) + 1
            cache[(curso_id, tema.strip())] = {
                "res": res, "geracao": st.session_state.geracao_questoes}

    chave = (curso_id, tema.strip())
    if not (tema.strip() and chave in cache):
        return
    res, geracao = cache[chave]["res"], cache[chave]["geracao"]
    if res["erro"]:
        st.error(res["erro"])
        return
    gerador = res["resultados"].get("gerador") or {}
    if gerador.get("status") != "ok":
        st.warning(gerador.get("mensagem") or "Não foi possível gerar as questões.")
    for i, q in enumerate(gerador.get("questoes", []), start=1):
        _cartao_questao(f"g{geracao}_{curso_id}_{tema.strip()}_{i}", i, q)


def _fonte(q: dict) -> None:
    ref = q.get("trecho_referencia") or {}
    if ref:
        st.caption(f"Onde estudar: {ref.get('arquivo')} · "
                   f"p.{ref.get('pagina')}-{ref.get('pagina_fim')}")


def _cartao_questao(rid: str, i: int, q: dict) -> None:
    """`rid` já inclui o id da geração, então cada rodada começa limpa."""
    conferidas = estado("questoes_conferidas")   # rid -> alternativa marcada / True
    with st.container(border=True):
        st.markdown(f"**Questão {i}** · {q.get('assunto', '')}")
        st.markdown(q.get("enunciado", ""))

        if q.get("tipo") == "multipla_escolha":
            _questao_multipla(rid, q, conferidas)
        else:
            _questao_discursiva(rid, q, conferidas)


def _questao_multipla(rid: str, q: dict, conferidas: dict) -> None:
    alternativas = q.get("alternativas", {})
    correta = q.get("correta")
    st.radio("Alternativas", list(alternativas),
             format_func=lambda k, a=alternativas: f"{k}) {a[k]}",
             key=f"rad_{rid}", label_visibility="collapsed", index=None)

    if st.button("Conferir resposta", key=f"conf_{rid}"):
        marcada = st.session_state.get(f"rad_{rid}")
        if marcada is None:
            st.warning("Escolha uma alternativa antes de conferir.")
        else:
            conferidas[rid] = marcada          # trava o veredito no momento do clique

    if rid not in conferidas:
        return
    marcada = conferidas[rid]
    if marcada == correta:
        st.success(f"Acertou! A resposta é **{correta}**) {alternativas.get(correta, '')}")
    else:
        st.error(f"Você marcou **{marcada}**) {alternativas.get(marcada, '')}")
        st.success(f"Resposta correta: **{correta}**) {alternativas.get(correta, '')}")
    explicacao = _primeiro_campo(q, CAMPOS_EXPLICACAO)
    if explicacao:
        st.info(f"**Por quê:** {explicacao}")
    _fonte(q)


def _questao_discursiva(rid: str, q: dict, conferidas: dict) -> None:
    minha = st.text_area("Sua resposta", key=f"txt_{rid}", height=130,
                         placeholder="Escreva sua resposta aqui antes de ver o gabarito...")

    if st.button("Ver resposta esperada", key=f"ver_{rid}"):
        if not minha.strip():
            st.warning("Escreva sua resposta primeiro. Comparar com o gabarito ajuda mais.")
        else:
            conferidas[rid] = True

    if rid not in conferidas:
        return
    gabarito = _primeiro_campo(q, CAMPOS_GABARITO)
    if gabarito:
        st.success(f"**Resposta esperada:** {gabarito}")
    else:
        st.info("Esta questão veio sem gabarito do gerador. "
                "Compare sua resposta com o trecho do material abaixo.")
    explicacao = _primeiro_campo(q, CAMPOS_EXPLICACAO)
    if explicacao:
        st.info(f"**Por quê:** {explicacao}")
    _fonte(q)


# --------------------------------------------------------------------------
# Página
# --------------------------------------------------------------------------
def main() -> None:
    curso_id, curso_nome = barra_lateral()
    if curso_id is None:
        st.title("🦉 Glaux")
        st.info("Selecione uma matéria na barra lateral para começar.")
        return

    cabecalho(curso_id, curso_nome)
    cartao_sincronizacao()

    aba_mat, aba_res, aba_praz, aba_quest = st.tabs(
        ["Materiais", "Resumo por tema", "Prazos", "Questões"])
    with aba_mat:
        aba_materiais(curso_id, curso_nome)
    with aba_res:
        aba_resumo(curso_id, curso_nome)
    with aba_praz:
        aba_prazos(curso_id, curso_nome)
    with aba_quest:
        aba_questoes(curso_id, curso_nome)


if __name__ == "__main__":
    main()