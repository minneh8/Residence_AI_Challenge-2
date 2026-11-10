# src/agente_canvas/service.py
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from canvasapi import Canvas
from src.agente_canvas.converter import PDFToMarkdownConverter  # 👈 Import absoluto
from src.state import CanvasCourse
from canvasapi.exceptions import CanvasException


class CanvasService:
    def __init__(
        self,
        api_url: str = "https://canvas.instructure.com",
        api_key: str = None,
        raw_dir: str = "data/raw",
        processed_dir: str = "data/processed",
    ):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key or os.getenv("CANVAS_API_KEY")
        self.raw_dir = Path(raw_dir)
        self.processed_dir = Path(processed_dir)

        if not self.api_key:
            raise ValueError("CANVAS_API_KEY não foi configurada.")

        self.canvas = Canvas(self.api_url, self.api_key)
        self.converter = PDFToMarkdownConverter(
            raw_dir=self.raw_dir, processed_dir=self.processed_dir
        )

    def get_user_courses(self) -> List[CanvasCourse]:
        """Busca matérias ativas do usuário, removendo canais institucionais e canceladas."""
        try:
            courses = self.canvas.get_courses(enrollment_state="active")
            valid_courses: List[CanvasCourse] = []
            seen_course_ids = set()
            seen_course_names = set()

            IGNORED_KEYWORDS = [
                "canal", "atualização", "atualizacao", "conectaref", 
                "comunidade", "orientações", "orientacoes", "cancelado", "cancelada"
            ]

            for c in courses:
                course_name = getattr(c, "name", "").strip()
                name_lower = course_name.lower()
                course_id = getattr(c, "id", None)

                if not course_name or not course_id:
                    continue

                if any(keyword in name_lower for keyword in IGNORED_KEYWORDS):
                    continue

                if course_id in seen_course_ids or course_name in seen_course_names:
                    continue

                seen_course_ids.add(course_id)
                seen_course_names.add(course_name)

                valid_courses.append(
                    CanvasCourse(
                        id=course_id,
                        name=course_name,
                        course_code=getattr(c, "course_code", None),
                    )
                )

            return valid_courses

        except CanvasException as e:
            print(f" [Erro Canvas API] Falha na autenticação ou conexão com o Canvas: {e}")
            return []

    def fetch_and_save_course_data(self, course_id: int) -> List[str]:
        """Baixa tarefas, avisos e PDFs do curso no Canvas, acionando o conversor para .MD em seguida."""
        course = self.canvas.get_course(course_id)
        course_folder = self.raw_dir / str(course_id)
        course_folder.mkdir(parents=True, exist_ok=True)
        downloaded_paths = []

        # 1. Salva Tarefas (Assignments)
        assignments = course.get_assignments()
        assignments_data = [
            {
                "id": a.id,
                "name": getattr(a, "name", ""),
                "due_at": getattr(a, "due_at", None),
                "submitted": getattr(a, "has_submitted_submissions", False),
            }
            for a in assignments
        ]
        with open(course_folder / "assignments.json", "w", encoding="utf-8") as f:
            json.dump(assignments_data, f, ensure_ascii=False, indent=2)

        # 2. Salva Arquivos (PDFs)
        try:
            files = course.get_files()
            for file in files:
                filename = getattr(file, "display_name", file.filename)
                if filename.lower().endswith(".pdf"):
                    dest_path = course_folder / filename
                    file.download(str(dest_path))
                    downloaded_paths.append(str(dest_path))
                    print(f" [Canvas] PDF Baixado: {filename}")
        except Exception as e:
            print(f" Aviso ao baixar arquivos do curso {course_id}: {e}")

        # 3.  ACIONA A CONVERSÃO DE PDF PARA MARKDOWN AUTOMATICAMENTE
        converted_mds = self.converter.convert_course_pdfs(course_id)
        downloaded_paths.extend([str(p) for p in converted_mds])

        return downloaded_paths