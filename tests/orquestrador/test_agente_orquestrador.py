# tests/orquestrador/test_agente_orquestrador.py
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.state import CanvasCourse, GlauxState
from src.agente_orquestrador.service import OrchestratorService
from src.agente_orquestrador.node import orchestrator_node


def test_plano_sincronizar_canvas_inclui_indexacao_rag(tmp_path):
    service = OrchestratorService(raw_dir=str(tmp_path), chroma_dir=str(tmp_path / "chroma"))
    state = GlauxState(user_id="u1", action="SINCRONIZAR_CANVAS")

    plano = service.build_execution_plan(state)
    assert plano.steps == ["canvas_agent", "rag_index_node"]


def test_plano_gerar_resumo_sem_pdfs_locais_injeta_canvas_e_rag(tmp_path):
    service = OrchestratorService(raw_dir=str(tmp_path), chroma_dir=str(tmp_path / "chroma"))
    state = GlauxState(user_id="u1", action="GERAR_RESUMO", curso_alvo=96829)

    plano = service.build_execution_plan(state)
    assert plano.steps == ["canvas_agent", "rag_index_node", "tutor_agent"]


def test_plano_gerar_resumo_com_pdf_local_mas_sem_indice_rag(tmp_path):
    conteudo_dir = tmp_path / "96829" / "conteudo"
    conteudo_dir.mkdir(parents=True)
    (conteudo_dir / "aula01.pdf").write_bytes(b"%PDF-1.4 fake")

    service = OrchestratorService(raw_dir=str(tmp_path), chroma_dir=str(tmp_path / "chroma"))
    with patch.object(service, "is_course_indexed_in_rag", return_value=False):
        state = GlauxState(user_id="u1", action="GERAR_RESUMO", curso_alvo=96829)
        plano = service.build_execution_plan(state)

    assert plano.steps == ["rag_index_node", "tutor_agent"]


def test_plano_gerar_resumo_com_rag_ja_indexado_vai_direto_pro_tutor(tmp_path):
    conteudo_dir = tmp_path / "96829" / "conteudo"
    conteudo_dir.mkdir(parents=True)
    (conteudo_dir / "aula01.pdf").write_bytes(b"%PDF-1.4 fake")

    service = OrchestratorService(raw_dir=str(tmp_path), chroma_dir=str(tmp_path / "chroma"))
    with patch.object(service, "is_course_indexed_in_rag", return_value=True):
        state = GlauxState(user_id="u1", action="GERAR_RESUMO", curso_alvo=96829)
        plano = service.build_execution_plan(state)

    assert plano.steps == ["tutor_agent"]


def test_plano_gerar_questoes_com_rag_e_resumo_prontos_vai_direto_pro_gerador(tmp_path):
    conteudo_dir = tmp_path / "96829" / "conteudo"
    conteudo_dir.mkdir(parents=True)
    (conteudo_dir / "aula01.pdf").write_bytes(b"%PDF-1.4 fake")

    service = OrchestratorService(raw_dir=str(tmp_path), chroma_dir=str(tmp_path / "chroma"))
    with patch.object(service, "is_course_indexed_in_rag", return_value=True):
        state = GlauxState(
            user_id="u1",
            action="GERAR_QUESTOES",
            curso_alvo=96829,
            summaries=[{"course_id": 96829, "summary_text": "Resumo pronto"}],
        )
        plano = service.build_execution_plan(state)

    assert plano.steps == ["question_generator_agent"]


def test_resolve_course_id_pelo_nome_da_materia(tmp_path):
    service = OrchestratorService(raw_dir=str(tmp_path))
    state = GlauxState(
        user_id="u1",
        action="GERAR_CRONOGRAMA",
        target_subject="Banco de Dados",
        courses=[CanvasCourse(id=96829, name="ESTUDOS DE BANCO DE DADOS I")],
    )

    plano = service.build_execution_plan(state)
    assert plano.resolved_course_id == 96829


def test_ciclo_de_consumo_da_fila_no_orchestrator_node():
    with patch("src.agente_orquestrador.node.OrchestratorService") as mock_srv_cls:
        mock_srv = MagicMock()
        mock_srv.build_execution_plan.return_value.steps = ["rag_index_node", "tutor_agent"]
        mock_srv.build_execution_plan.return_value.resolved_course_id = 96829
        mock_srv.build_execution_plan.return_value.reason = "Teste de ciclo"
        mock_srv_cls.return_value = mock_srv

        state1 = GlauxState(user_id="u1", action="GERAR_RESUMO", curso_alvo=96829)
        out1 = orchestrator_node(state1)
        assert out1["next_node"] == "rag_index_node"
        assert out1["execution_plan"] == ["tutor_agent"]

        state2 = state1.model_copy(update=out1)
        out2 = orchestrator_node(state2)
        assert out2["next_node"] == "tutor_agent"
        assert out2["execution_plan"] == []

        state3 = state2.model_copy(update=out2)
        out3 = orchestrator_node(state3)
        assert out3["next_node"] == "END"


def test_grafo_completo_roteamento_condicional():
    with (
        patch("src.graph.canvas_agent_node", return_value={"courses": [{"id": 96829, "name": "BD I"}]}) as mock_canvas,
        patch("src.graph.rag_index_node", return_value={"rag_indexed_courses": [96829]}) as mock_rag,
        patch("src.graph.tutor_agent_node", return_value={"summaries": [{"course_id": 96829}]}) as mock_tutor,
        patch("src.agente_orquestrador.service.OrchestratorService.has_local_data", return_value=True),
        patch("src.agente_orquestrador.service.OrchestratorService.is_course_indexed_in_rag", return_value=True),
    ):
        from src.graph import build_glaux_graph

        app = build_glaux_graph()
        final_state = app.invoke(
            GlauxState(user_id="u1", action="GERAR_RESUMO", curso_alvo=96829)
        )

        mock_canvas.assert_not_called()
        mock_rag.assert_not_called()
        mock_tutor.assert_called_once()
        assert final_state["next_node"] == "END"