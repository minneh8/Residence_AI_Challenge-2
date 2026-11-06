# src/agente_canvas/service.py
import os
import sys
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional
from canvasapi import Canvas
import json
from src.state import CanvasCourse, CanvasFileMetadata, CanvasAssignment, CanvasAnnouncement

# Garante que a raiz do projeto esteja no PYTHONPATH para os imports
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from src.state import CanvasCourse, CanvasFileMetadata


class CanvasService:
    """
    Serviço responsável por interagir diretamente com a API do Canvas LMS.
    """
    def __init__(self, api_url: Optional[str] = None, api_key: Optional[str] = None, base_data_dir: str = "data/raw"):
        self.api_url = api_url or os.getenv("CANVAS_API_URL", "https://canvas.instructure.com")
        self.api_key = api_key or os.getenv("CANVAS_API_KEY")
        
        if not self.api_key:
            raise ValueError(" Token de acesso do Canvas LMS (CANVAS_API_KEY) não foi fornecido.")

        self.canvas = Canvas(self.api_url, self.api_key)
        self.user = self.canvas.get_current_user()
        
        # Aponta para data/raw conforme a estrutura do projeto
        self.base_data_dir = Path(base_data_dir)

    def get_user_courses(self) -> List[CanvasCourse]:
        """
        Captura todas as matérias ativas do aluno.
        """
        courses = self.user.get_courses(enrollment_state="active")
        parsed_courses: List[CanvasCourse] = []

        for course in courses:
            course_name = getattr(course, "name", None)
            course_id = getattr(course, "id", None)

            if not course_id or not course_name:
                continue

            parsed_courses.append(CanvasCourse(id=course_id, name=course_name))

        return parsed_courses

    def download_files_from_course(self, course_info: CanvasCourse) -> List[CanvasFileMetadata]:
        """
        Baixa os PDFs de uma única matéria específica para a pasta data/raw/{course_id}.
        Se a pasta existir, apenas insere; se não existir, cria e insere.
        """
        downloaded_files_metadata: List[CanvasFileMetadata] = []
        course_id = course_info.id
        course_name = course_info.name

        print(f"\n Processando Matéria: [{course_name}] | (ID: {course_id})")

        # Define o caminho data/raw/{course_id} e cria se não existir
        course_dir = self.base_data_dir / str(course_id)
        course_dir.mkdir(parents=True, exist_ok=True)

        try:
            course = self.canvas.get_course(course_id)
            files = course.get_files()
            
            pdf_count = 0
            for file in files:
                filename = getattr(file, "display_name", getattr(file, "filename", ""))
                
                if filename.lower().endswith(".pdf"):
                    download_url = getattr(file, "url", None)
                    if not download_url:
                        continue

                    file_path = course_dir / filename

                    # Só baixa se o arquivo ainda não existir dentro da pasta do ID
                    if not file_path.exists():
                        print(f"   Baixando: {filename} ...")
                        response = requests.get(download_url, headers={"Authorization": f"Bearer {self.api_key}"})
                        if response.status_code == 200:
                            with open(file_path, "wb") as f:
                                f.write(response.content)
                            print(f"   Salvo em: {file_path}")
                        else:
                            print(f"   Falha no download de {filename} (Status: {response.status_code})")
                    else:
                        print(f"   Arquivo já existente: {filename}")

                    pdf_count += 1
                    downloaded_files_metadata.append(
                        CanvasFileMetadata(
                            course_id=course_id,
                            filename=filename,
                            url=str(file_path)
                        )
                    )

            if pdf_count == 0:
                print("    Nenhum PDF encontrado nesta matéria.")

        except Exception as e:
            print(f"   Não foi possível acessar arquivos da matéria {course_name}: {e}")

        print("-" * 60)
        return downloaded_files_metadata

    def download_course_files(self, selected_course_id: Optional[int] = None) -> List[CanvasFileMetadata]:

        courses = self.get_user_courses()

        if selected_course_id:
            target_course = next((c for c in courses if c.id == selected_course_id), None)
            if target_course:
                return self.download_files_from_course(target_course)
            else:
                print(f" Matéria com ID {selected_course_id} não foi encontrada entre as matérias ativas.")
                return []

        print(f"\n [Agente Canvas] Baixando PDFs de todas as {len(courses)} matérias...\n")
        all_metadata: List[CanvasFileMetadata] = []
        for course in courses:
            all_metadata.extend(self.download_files_from_course(course))
        
        return all_metadata

    def get_course_assignments(self, course_info: CanvasCourse) -> List[CanvasAssignment]:
        """
        Captura as tarefas e prazos de entrega de uma matéria específica 
        e salva um arquivo assignments.json na pasta da matéria.
        """
        course_id = course_info.id
        course_dir = self.base_data_dir / str(course_id)
        course_dir.mkdir(parents=True, exist_ok=True)

        parsed_assignments: List[CanvasAssignment] = []

        try:
            course = self.canvas.get_course(course_id)
            assignments = course.get_assignments()

            print(f" Puxando tarefas da matéria [{course_info.name}]...")
            for assign in assignments:
                due_at = getattr(assign, "due_at", None)
                
                # Verifica se o aluno já enviou a tarefa
                has_submitted = False
                submission = getattr(assign, "submission", None)
                if submission and getattr(submission, "workflow_state", "") == "submitted":
                    has_submitted = True

                item = CanvasAssignment(
                    id=assign.id,
                    course_id=course_id,
                    title=getattr(assign, "name", "Sem Título"),
                    description=getattr(assign, "description", ""),
                    due_at=due_at,
                    points_possible=getattr(assign, "points_possible", None),
                    submitted=has_submitted
                )
                parsed_assignments.append(item)

            # Salva a lista de tarefas em um JSON estruturado dentro de data/raw/{course_id}/assignments.json
            json_path = course_dir / "assignments.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump([a.model_dump() for a in parsed_assignments], f, ensure_ascii=False, indent=2)

            print(f"    {len(parsed_assignments)} tarefas registradas em: {json_path}")

        except Exception as e:
            print(f"    Não foi possível buscar tarefas da matéria {course_info.name}: {e}")

        return parsed_assignments

    def get_course_announcements(self, course_info: CanvasCourse) -> List[CanvasAnnouncement]:
        """
        Captura avisos e recados dos professores (onde geralmente informam datas de provas)
        e salva um arquivo announcements.json na pasta da matéria.
        """
        course_id = course_info.id
        course_dir = self.base_data_dir / str(course_id)
        course_dir.mkdir(parents=True, exist_ok=True)

        parsed_announcements: List[CanvasAnnouncement] = []

        try:
            # A API do Canvas exige a busca de avisos usando o contexto do curso
            announcements = self.canvas.get_announcements(context_codes=[f"course_{course_id}"])

            print(f" Puxando avisos da matéria [{course_info.name}]...")
            for ann in announcements:
                item = CanvasAnnouncement(
                    id=ann.id,
                    course_id=course_id,
                    title=getattr(ann, "title", "Aviso"),
                    message=getattr(ann, "message", ""),
                    posted_at=getattr(ann, "posted_at", "")
                )
                parsed_announcements.append(item)

            # Salva os avisos em JSON em data/raw/{course_id}/announcements.json
            json_path = course_dir / "announcements.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump([a.model_dump() for a in parsed_announcements], f, ensure_ascii=False, indent=2)

            print(f"    {len(parsed_announcements)} avisos registrados em: {json_path}")

        except Exception as e:
            print(f"    Não foi possível buscar avisos da matéria {course_info.name}: {e}")

        return parsed_announcements


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    service = CanvasService()
    materias = service.get_user_courses()

    if not materias:
        print(" Nenhuma matéria ativa encontrada.")
        sys.exit(0)

    print("\n================ MATÉRIAS DISPONÍVEIS ================")
    for idx, m in enumerate(materias, 1):
        print(f"[{idx}] ID: {m.id} | Nome: {m.name}")
    print("[0] Processar TODAS as matérias (PDFs, Tarefas e Avisos)")
    print("======================================================")

    opcao = input("Digite o número da opção desejada: ").strip()

    def processar_materia_completa(curso: CanvasCourse):
        """Executa a coleta completa (PDFs, Tarefas e Avisos) para uma matéria."""
        print(f"\n Iniciando processamento completo da matéria: {curso.name} (ID: {curso.id})")
        service.download_files_from_course(curso)
        service.get_course_assignments(curso)
        service.get_course_announcements(curso)
        print(f" Matéria [{curso.name}] processada com sucesso!")

    match opcao:
        case "0":
            print("\n Iniciando processamento completo de TODAS as matérias...")
            for materia in materias:
                processar_materia_completa(materia)
            print("\n Processamento de todas as disciplinas concluído!")
            
        case x if x.isdigit() and 1 <= int(x) <= len(materias):
            materia_escolhida = materias[int(x) - 1]
            processar_materia_completa(materia_escolhida)
            
        case _:
            print("\n Opção inválida! Encerrando...")