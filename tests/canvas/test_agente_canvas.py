# tests/test_agente_canvas.py
import fitz
from pathlib import Path
from unittest.mock import MagicMock, patch
from src.agente_canvas.service import CanvasService

DOCS_DIR = Path("data/raw")


def classificar_pdf_canvas(pdf_path: Path) -> str:
    """
    Lê as primeiras páginas do PDF real da pasta docs/ e classifica em:
    - LISTA_EXERCICIOS: listas, exercícios, provas, estudos dirigidos
    - CONTEUDO_BASE: slides de aula, apostilas, planos de ensino
    """
    doc = fitz.open(str(pdf_path))
    texto_inicial = ""
    for i in range(min(2, len(doc))):  # Lê até as 2 primeiras páginas
        texto_inicial += doc[i].get_text().lower() + "\n"
    doc.close()

    palavras_chave_lista = [
        "lista de exercícios",
        "lista de exercicios",
        "questão 1",
        "questao 1",
        "exercício 1",
        "exercicio 1",
        "assinale a alternativa",
        "atividade de laboratório",
        "atividade laboratorio",
        "estudo dirigido",
    ]

    if any(palavra in texto_inicial for palavra in palavras_chave_lista):
        return "LISTA_EXERCICIOS"
    return "CONTEUDO_BASE"


def test_classificacao_pdfs_reais_em_docs():
    """
    Varre todos os PDFs reais presentes em docs/ e valida se o classificador
    atribui categorias válidas (CONTEUDO_BASE ou LISTA_EXERCICIOS) para cada um.
    """
    assert DOCS_DIR.exists(), "A pasta 'docs/' não foi encontrada na raiz do projeto."

    pdfs = [f for f in DOCS_DIR.rglob("*") if f.is_file() and f.suffix.lower() == ".pdf"]
    assert len(pdfs) > 0, "Nenhum arquivo .pdf encontrado dentro de docs/."

    print(f"\n📂 Classificando {len(pdfs)} PDFs reais encontrados em docs/:")
    for pdf in pdfs:
        categoria = classificar_pdf_canvas(pdf)
        print(f"   📄 {pdf.name}  --->  [{categoria}]")
        assert categoria in ["CONTEUDO_BASE", "LISTA_EXERCICIOS"]


@patch("src.agente_canvas.service.Canvas")
def test_canvas_puxa_e_salva_pdfs(mock_canvas_cls, tmp_path):
    """
    Simula o retorno da API do Canvas usando os nomes dos PDFs reais de docs/
    e verifica se o CanvasService captura e salva na pasta do course_id.
    """
    pdfs_reais = [f for f in DOCS_DIR.rglob("*") if f.is_file() and f.suffix.lower() == ".pdf"]
    pdf_exemplo = pdfs_reais[0]

    course_id = 96829
    mock_instance = MagicMock()
    mock_canvas_cls.return_value = mock_instance

    curso_mock = MagicMock()
    curso_mock.id = course_id
    curso_mock.name = "218131P - ESTUDOS DE BANCO DE DADOS I"
    curso_mock.course_code = "218131P"

    arquivo_mock = MagicMock()
    arquivo_mock.filename = pdf_exemplo.name
    arquivo_mock.display_name = pdf_exemplo.name
    arquivo_mock.download.side_effect = lambda dest: Path(dest).write_bytes(pdf_exemplo.read_bytes())

    curso_mock.get_files.return_value = [arquivo_mock]
    curso_mock.get_assignments.return_value = []
    mock_instance.get_course.return_value = curso_mock

    # CANVAS_API_URL não tem mais valor padrão: o teste informa uma URL fictícia.
    service = CanvasService(
        api_url="https://canvas.test", api_key="token_fake", raw_dir=str(tmp_path)
    )
    service.fetch_and_save_course_data(course_id)

    # O agente separa os PDFs em conteudo/ (slides, livros) e listas/.
    arquivo_baixado = tmp_path / str(course_id) / "conteudo" / pdf_exemplo.name
    assert arquivo_baixado.exists(), f"O arquivo {pdf_exemplo.name} não foi salvo pelo agente."