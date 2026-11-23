# tests/canvas/test_agente_canvas.py
import pymupdf
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.agente_canvas.catalogo import Catalogo
from src.agente_canvas.classificador import classificar
from src.agente_canvas.service import CanvasService

DOCS_DIR = Path("data/raw")
PDFS_REAIS = (
    sorted(f for f in DOCS_DIR.rglob("*") if f.is_file() and f.suffix.lower() == ".pdf")
    if DOCS_DIR.exists() else []
)
CATEGORIAS_REGRAS = {"slides", "listas", "trabalho", "livros", "indefinido"}


def _contar_paginas(pdf_path: Path):
    with pymupdf.open(str(pdf_path)) as doc:
        return len(doc)


@pytest.mark.skipif(not PDFS_REAIS, reason="sem PDFs reais em data/raw/ nesta máquina")
def test_classificacao_pdfs_reais_em_docs():
    """
    Varre todos os PDFs reais presentes em data/raw/ e valida se o classificador
    por regras (classificador.py) devolve uma categoria válida para cada um,
    usando nome, tamanho e número de páginas reais.
    """
    print(f"\n📂 Classificando {len(PDFS_REAIS)} PDFs reais encontrados em data/raw/:")
    for pdf in PDFS_REAIS:
        categoria, origem = classificar(
            pdf.name, tamanho=pdf.stat().st_size, paginas=_contar_paginas(pdf))
        print(f"   📄 {pdf.name}  --->  [{categoria} | {origem}]")
        assert categoria in CATEGORIAS_REGRAS


def _pdf_exemplo(tmp_path: Path) -> Path:
    """Um PDF real de aula em data/raw/ se houver; senão, um PDF gerado na hora.

    Usa um "aula*.pdf" para que o nome não decida antes do módulo (ex.:
    "ex_aula03.pdf" vira listas pela regra de nome).
    """
    real = next((p for p in PDFS_REAIS if p.name.lower().startswith("aula")), None)
    if real:
        return real
    caminho = tmp_path / "aula_exemplo.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Aula de exemplo")
    doc.save(caminho)
    doc.close()
    return caminho


@patch("src.agente_canvas.service.Canvas")
def test_canvas_puxa_e_salva_pdfs(mock_canvas_cls, tmp_path):
    """
    Simula o retorno da API do Canvas com um PDF real de data/raw/ e verifica se
    o CanvasService baixa, classifica pelo módulo e salva em
    data/raw/<course_id>/<categoria>/, registrando no catálogo do curso.
    """
    pdf_exemplo = _pdf_exemplo(tmp_path)
    course_id = 96829
    file_id = 4252625

    mock_instance = MagicMock()
    mock_canvas_cls.return_value = mock_instance
    mock_instance.get_current_user.return_value = SimpleNamespace(id=1001, name="Aluno Teste")

    curso_mock = MagicMock()
    curso_mock.id = course_id
    curso_mock.name = "218131P - ESTUDOS DE BANCO DE DADOS I"
    curso_mock.course_code = "218131P"

    arquivo_mock = MagicMock()
    arquivo_mock.id = file_id
    arquivo_mock.filename = pdf_exemplo.name
    arquivo_mock.display_name = pdf_exemplo.name
    arquivo_mock.updated_at = "2026-09-10T14:11:25Z"
    arquivo_mock.size = pdf_exemplo.stat().st_size
    arquivo_mock.download.side_effect = lambda dest: Path(dest).write_bytes(pdf_exemplo.read_bytes())

    curso_mock.get_files.return_value = [arquivo_mock]
    curso_mock.get_modules.return_value = [
        SimpleNamespace(name="Slides de Aula", items=[{"type": "File", "content_id": file_id}])
    ]
    curso_mock.get_assignments.return_value = []
    mock_instance.get_course.return_value = curso_mock

    service = CanvasService(
        api_url="https://canvas.test", api_key="token_fake",
        raw_dir=str(tmp_path / "raw"), state_dir=str(tmp_path / "estado"),
        classificador_llm=lambda *a, **k: {"categoria": "outros", "origem": "llm"},
    )
    resumo = service.sincronizar_curso(course_id)

    curso_mock.get_files.assert_called_once_with(sort="updated_at", order="desc")
    arquivo_baixado = tmp_path / "raw" / str(course_id) / "slides" / pdf_exemplo.name
    assert arquivo_baixado.exists(), f"O arquivo {pdf_exemplo.name} não foi salvo pelo agente."
    assert resumo["novos"] == [pdf_exemplo.name] and resumo["estado_gravado"]

    entrada = Catalogo(tmp_path / "raw" / str(course_id)).get(file_id)
    assert entrada["categoria"] == "slides" and entrada["origem"] == "modulo:aula"
    assert entrada["caminho"] == f"slides/{pdf_exemplo.name}"
    assert entrada["updated_at"] == "2026-09-10T14:11:25Z"
