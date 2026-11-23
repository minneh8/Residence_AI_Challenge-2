# src/agente_canvas/converter.py
import sys
from pathlib import Path

# Garante inclusão do PYTHONPATH
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

try:
    import pymupdf4llm
except ImportError:
    pymupdf4llm = None


class PDFToMarkdownConverter:
    def __init__(self, raw_dir: str = "data/raw", processed_dir: str = "data/processed"):
        self.raw_dir = Path(raw_dir)
        self.processed_dir = Path(processed_dir)

    def convert_course_pdfs(self, course_id: int) -> list[Path]:
        """Converte todos os PDFs da pasta raw de um curso para arquivos .md na pasta processed."""
        course_raw = self.raw_dir / str(course_id)
        course_processed = self.processed_dir / str(course_id)

        if not course_raw.exists():
            print(f" Pasta raw não encontrada para o curso: {course_id}")
            return []

        course_processed.mkdir(parents=True, exist_ok=True)
        converted_files = []

        if pymupdf4llm is None:
            print(" Erro: 'pymupdf4llm' não instalado. Execute: pip install pymupdf4llm")
            return []

        # Busca arquivos com extensão .pdf ou .PDF
        pdf_files = list(course_raw.glob("*.pdf")) + list(course_raw.glob("*.PDF"))

        for pdf_path in pdf_files:
            md_filename = f"{pdf_path.stem}.md"
            md_path = course_processed / md_filename

            try:
                # Converte PDF em texto Markdown
                md_text = pymupdf4llm.to_markdown(str(pdf_path))
                
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(md_text)

                converted_files.append(md_path)
                print(f" [Converter] Convertido com sucesso: {pdf_path.name} -> {md_filename}")
            except Exception as e:
                print(f" [Converter] Erro ao converter {pdf_path.name}: {e}")

        return converted_files