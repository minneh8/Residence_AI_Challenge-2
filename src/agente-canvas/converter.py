# src/agente_canvas/converter.py
import sys
from pathlib import Path
import pymupdf4llm

# Garante que a raiz do projeto esteja no PYTHONPATH
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))


class PDFToMarkdownConverter:
    """
    Serviço para converter arquivos PDF contidos em data/raw/{course_id}
    em arquivos Markdown (.md) em data/processed/{course_id}.
    """
    def __init__(self, raw_dir: str = "data/raw", processed_dir: str = "data/processed"):
        self.raw_dir = Path(raw_dir)
        self.processed_dir = Path(processed_dir)

    def convert_course_pdfs(self, course_id: int):
        """
        Converte todos os PDFs da pasta de uma matéria específica para Markdown.
        """
        source_folder = self.raw_dir / str(course_id)
        target_folder = self.processed_dir / str(course_id)

        if not source_folder.exists():
            print(f" Pasta de origem {source_folder} não existe.")
            return

        target_folder.mkdir(parents=True, exist_ok=True)
        pdf_files = [f for f in source_folder.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]

        print(f"\n Convertendo {len(pdf_files)} PDFs da matéria {course_id} para Markdown...")

        for pdf_path in pdf_files:
            md_filename = pdf_path.stem + ".md"
            md_path = target_folder / md_filename

            # Evita reconverter se o arquivo .md já existir
            if not md_path.exists():
                try:
                    print(f"    Convertendo: {pdf_path.name} ...")
                    # Converte o PDF diretamente para string Markdown
                    md_text = pymupdf4llm.to_markdown(str(pdf_path))

                    # Salva o resultado no arquivo .md
                    with open(md_path, "w", encoding="utf-8") as f:
                        f.write(md_text)

                    print(f"    Salvo em: {md_path}")
                except Exception as e:
                    print(f"    Erro ao converter {pdf_path.name}: {e}")
            else:
                print(f"    Markdown já existente: {md_filename}")

    def convert_all(self):
        """
        Varre todas as pastas em data/raw/ e realiza a conversão.
        """
        if not self.raw_dir.exists():
            print(f" Diretório {self.raw_dir} não encontrado.")
            return

        course_folders = [f for f in self.raw_dir.iterdir() if f.is_dir()]
        for folder in course_folders:
            if folder.name.isdigit():
                self.convert_course_pdfs(int(folder.name))


if __name__ == "__main__":
    converter = PDFToMarkdownConverter()
    print(" Iniciando conversão de PDFs para Markdown...")
    converter.convert_all()
    print("\n Conversão concluída com sucesso!")