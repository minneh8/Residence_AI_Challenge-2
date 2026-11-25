"""Testes da camada de ações da interface (src/interface/acoes.py).

Tudo roda offline: os agentes são substituídos por dublês que só registram a
ordem das chamadas. Nada acessa o Canvas, o Groq, o RAG, o .env ou data/raw real.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agente_canvas.service import CanvasAuthError, CanvasConfigError
from src.interface import acoes


# --------------------------------------------------------------------------
# Dublês dos agentes
# --------------------------------------------------------------------------
def agentes_que_registram(chamadas, updates_por_agente=None):
    """Mapa nome->agente falso que anota a ordem e devolve updates opcionais."""
    updates_por_agente = updates_por_agente or {}

    def fazer(nome):
        def agente(state):
            chamadas.append(nome)
            return {"updates": updates_por_agente.get(nome, {}),
                    "resultado": {"agente": nome}}
        return agente

    return {nome: fazer(nome) for nome in ("canvas", "tutor", "gerador")}


def agente_que_quebra(chamadas, excecao):
    """Canvas falso que registra a chamada e levanta `excecao`."""
    def agente(state):
        chamadas.append("canvas")
        raise excecao
    return {"canvas": agente, "tutor": lambda s: {"updates": {}, "resultado": {}},
            "gerador": lambda s: {"updates": {}, "resultado": {}}}


# --------------------------------------------------------------------------
# planejar(): qual agente roda em cada ação
# --------------------------------------------------------------------------
def test_sincronizar_so_chama_canvas():
    assert acoes.planejar("SINCRONIZAR_CANVAS") == ["canvas"]


def test_resumo_pula_canvas_quando_ha_pdfs():
    assert acoes.planejar("GERAR_RESUMO", tem_pdfs=True) == ["tutor"]


def test_resumo_inclui_canvas_sem_pdfs():
    assert acoes.planejar("GERAR_RESUMO", tem_pdfs=False) == ["canvas", "tutor"]


def test_forcar_sempre_inclui_canvas():
    assert acoes.planejar("GERAR_RESUMO", tem_pdfs=True, forcar=True) == ["canvas", "tutor"]


def test_questoes_nao_passam_pelo_tutor():
    # O Gerador lê o RAG direto; o Tutor fica de fora (ver docstring de planejar).
    assert acoes.planejar("GERAR_QUESTOES", tem_pdfs=True) == ["gerador"]
    assert acoes.planejar("GERAR_QUESTOES", tem_pdfs=False) == ["canvas", "gerador"]


def test_fluxo_completo_com_e_sem_questoes():
    assert acoes.planejar("FLUXO_COMPLETO") == ["canvas", "tutor"]
    assert acoes.planejar("FLUXO_COMPLETO", com_questoes=True) == ["canvas", "tutor", "gerador"]


def test_acao_desconhecida():
    with pytest.raises(ValueError):
        acoes.planejar("NAO_EXISTE")


# --------------------------------------------------------------------------
# executar_acao(): ordem dos agentes
# --------------------------------------------------------------------------
def test_sincronizar_executa_so_canvas(tmp_path):
    chamadas = []
    res = acoes.executar_acao(
        "SINCRONIZAR_CANVAS", 93527, raw_dir=str(tmp_path),
        agentes=agentes_que_registram(chamadas),
    )
    assert chamadas == ["canvas"]
    assert res["agentes"] == ["canvas"]
    assert res["erro"] is None


def test_questoes_chamam_canvas_depois_gerador_sem_dados(tmp_path):
    chamadas = []
    res = acoes.executar_acao(
        "GERAR_QUESTOES", 999, tema="t", quantidade=3, raw_dir=str(tmp_path),
        agentes=agentes_que_registram(chamadas),
    )
    # tmp_path vazio: não há PDFs, então o Canvas entra antes do Gerador.
    assert chamadas == ["canvas", "gerador"]
    assert res["agentes"] == ["canvas", "gerador"]


def test_resumo_pula_canvas_com_pdfs_no_disco(tmp_path):
    pdf = tmp_path / "93527" / "slides" / "aula00.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 fake")
    chamadas = []
    res = acoes.executar_acao(
        "GERAR_RESUMO", 93527, tema="hipótese nula", raw_dir=str(tmp_path),
        course_name="Métodos", agentes=agentes_que_registram(chamadas),
    )
    assert chamadas == ["tutor"]
    assert res["agentes"] == ["tutor"]


def test_estado_do_curso_montado_quando_canvas_nao_roda(tmp_path):
    pdf = tmp_path / "77" / "slides" / "a.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 fake")
    cursos_vistos = {}

    def tutor(state):
        cursos_vistos["courses"] = list(state.courses)
        return {"updates": {}, "resultado": {}}

    agentes = agentes_que_registram([])
    agentes["tutor"] = tutor
    acoes.executar_acao(
        "GERAR_RESUMO", 77, tema="x", raw_dir=str(tmp_path),
        course_name="Disciplina 77", agentes=agentes,
    )
    assert len(cursos_vistos["courses"]) == 1
    assert cursos_vistos["courses"][0].id == 77
    assert cursos_vistos["courses"][0].name == "Disciplina 77"


# --------------------------------------------------------------------------
# executar_acao(): propagação de estado e tempos
# --------------------------------------------------------------------------
def test_updates_propagam_entre_agentes(tmp_path):
    chamadas = []
    agentes = agentes_que_registram(
        chamadas, updates_por_agente={"canvas": {"downloaded_files": ["a.pdf"]}})
    vistos = {}

    def tutor(state):
        chamadas.append("tutor")
        vistos["downloaded_files"] = list(state.downloaded_files)
        return {"updates": {}, "resultado": {}}

    agentes["tutor"] = tutor
    acoes.executar_acao(
        "FLUXO_COMPLETO", 1, raw_dir=str(tmp_path), agentes=agentes)
    assert vistos["downloaded_files"] == ["a.pdf"]


def test_tempo_da_sincronizacao_vem_separado(tmp_path):
    res = acoes.executar_acao(
        "SINCRONIZAR_CANVAS", 1, raw_dir=str(tmp_path),
        agentes=agentes_que_registram([]),
    )
    assert res["tempo_sincronizacao"] == res["tempos"]["canvas"]
    assert res["tempo_sincronizacao"] is not None


# --------------------------------------------------------------------------
# executar_acao(): erros viram mensagens amigáveis (sem stack trace)
# --------------------------------------------------------------------------
def test_erro_de_token_vira_mensagem_amigavel(tmp_path):
    chamadas = []
    erro = CanvasAuthError("Token do Canvas ausente ou invalido. Confira CANVAS_API_KEY no .env")
    res = acoes.executar_acao(
        "SINCRONIZAR_CANVAS", 1, raw_dir=str(tmp_path),
        agentes=agente_que_quebra(chamadas, erro),
    )
    assert res["erro"] is not None
    assert "Token" in res["erro"]
    assert res["agentes"] == []  # nenhum agente concluiu


def test_erro_de_config_url(tmp_path):
    erro = CanvasConfigError("CANVAS_API_URL não definido. Informe no .env a URL da instituição")
    res = acoes.executar_acao(
        "SINCRONIZAR_CANVAS", 1, raw_dir=str(tmp_path),
        agentes=agente_que_quebra([], erro),
    )
    assert "CANVAS_API_URL" in res["erro"]


def test_erro_do_groq_vira_mensagem_amigavel(tmp_path):
    import groq

    def tutor(state):
        raise groq.GroqError("conexão recusada")

    agentes = agentes_que_registram([])
    agentes["tutor"] = tutor
    pdf = tmp_path / "5" / "slides" / "a.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 fake")
    res = acoes.executar_acao(
        "GERAR_RESUMO", 5, tema="x", raw_dir=str(tmp_path),
        course_name="C", agentes=agentes,
    )
    assert res["erro"] == acoes.MSG_ERRO_GROQ


def test_erro_generico_sem_stack_trace(tmp_path):
    def canvas(state):
        raise RuntimeError("algo inesperado")

    agentes = agentes_que_registram([])
    agentes["canvas"] = canvas
    res = acoes.executar_acao(
        "SINCRONIZAR_CANVAS", 1, raw_dir=str(tmp_path), agentes=agentes)
    assert "algo inesperado" in res["erro"]
    assert res["erro"].startswith("Não foi possível concluir a ação")
