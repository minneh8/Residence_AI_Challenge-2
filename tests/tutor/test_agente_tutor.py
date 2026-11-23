# tests/test_agente_tutor.py
import json
import pymupdf
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from src.state import CanvasCourse
from src.agente_tutor.service import TutorService


DOCS_DIR = Path("data/raw")


def extrair_contexto_real_de_docs(limite_chars: int = 2500):
    """Lê trechos reais dos PDFs em docs/ para alimentar o teste do RAG/Tutor."""
    pdfs = [f for f in DOCS_DIR.rglob("*") if f.is_file() and f.suffix.lower() == ".pdf"]
    assert len(pdfs) > 0, "Nenhum PDF encontrado em docs/ para testar o resumo."

    contexto = []
    fontes = []
    for pdf in pdfs[:2]:
        doc = pymupdf.open(str(pdf))
        texto = doc[0].get_text() if len(doc) > 0 else ""
        doc.close()
        if texto.strip():
            contexto.append(f"[Fonte: {pdf.name} | Pág. 1]\n{texto[:1000]}")
            fontes.append(pdf.name)

    return "\n\n".join(contexto)[:limite_chars], fontes


def test_tutor_avisa_prazos_proximos_e_ignora_vencidos(tmp_path):
    """
    Valida se o Agente Tutor:
    1. Ignora tarefas já vencidas (days_remaining < 0) ou já entregues.
    2. Classifica como ALTA prioridade e emite alerta para entregas próximas (<= 2 dias).
    """
    course_id = 96829
    course_dir = tmp_path / str(course_id)
    course_dir.mkdir(parents=True)

    now = datetime.now(timezone.utc)
    tarefas = [
        {
            "id": 1,
            "course_id": course_id,
            "title": "Tarefa Antiga Vencida",
            "due_at": (now - timedelta(days=2)).isoformat(),
            "submitted": False,
        },
        {
            "id": 2,
            "course_id": course_id,
            "title": "Entrega Urgente - Modelo Relacional",
            "due_at": (now + timedelta(days=1)).isoformat(),
            "submitted": False,
        },
        {
            "id": 3,
            "course_id": course_id,
            "title": "Projeto Final - SQL",
            "due_at": (now + timedelta(days=6)).isoformat(),
            "submitted": False,
        },
    ]

    with open(course_dir / "assignments.json", "w", encoding="utf-8") as f:
        json.dump(tarefas, f, ensure_ascii=False)

    tutor = TutorService(raw_dir=str(tmp_path))
    cronograma = tutor.generate_schedule([CanvasCourse(id=course_id, name="Banco de Dados I")])

    # Deve ignorar a tarefa vencida e manter apenas as 2 futuras
    assert len(cronograma) == 2

    # Primeira da fila deve ser a urgente (1 dia restante -> ALTA)
    assert cronograma[0].title == "Entrega Urgente - Modelo Relacional"
    assert cronograma[0].priority_level == "ALTA"
    assert cronograma[0].days_remaining <= 2


CURSO_INDEXADO = 93527


def _curso_indexado(course_id: int) -> bool:
    try:
        from src.rag.indexacao import curso_indexado
        return curso_indexado(course_id)
    except Exception:
        return False


@pytest.mark.skipif(not _curso_indexado(CURSO_INDEXADO),
                    reason=f"curso {CURSO_INDEXADO} não está indexado em data/chroma/")
@patch("src.agente_tutor.service.ChatGroq")
def test_tutor_gera_resumo_usando_rag_com_pdfs_de_docs(mock_groq_cls):
    """
    Valida se o Agente Tutor recupera o conteúdo da matéria (via RAG ou PDFs locais)
    e invoca a LLM (Groq) para gerar o resumo estruturado.
    """
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    # Cada frase cita a fonte: sem isso o Tutor pede uma reescrita (2ª chamada).
    mock_resp.content = (
        "# 📌 Visão Geral da Aula\n"
        "Resumo gerado com base no material da disciplina [aula03.pdf, p.15-15].\n\n"
        "# 🔑 Conceitos-Chave e Definições\n"
        "- Conteúdo extraído dos PDFs reais [aula03.pdf, p.15-15]."
    )
    mock_llm.invoke.return_value = mock_resp
    mock_groq_cls.return_value = mock_llm

    tutor = TutorService()
    resumo = tutor.generate_summary_for_course(
        CURSO_INDEXADO, "MÉTODOS DE COMPUTAÇÃO EXPERIMENTAL E QUANTITATIVA",
        tema="hipótese nula")

    assert resumo.course_id == CURSO_INDEXADO
    assert len(resumo.summary_text) > 0
    # Se houver fontes indexadas no RAG/data/raw para o curso 96829, valida que a LLM foi chamada
    if resumo.sources_used:
        mock_llm.invoke.assert_called_once()
        assert "Visão Geral da Aula" in resumo.summary_text