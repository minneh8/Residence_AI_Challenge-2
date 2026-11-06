# src/agente_canvas/node.py
from typing import Dict, Any
from src.state import GlauxState
from service import CanvasService

def canvas_agent_node(state: GlauxState) -> Dict[str, Any]:
    """
    Nó do LangGraph: Mapeia matérias, faz download de PDFs e extrai tarefas e avisos.
    """
    service = CanvasService(api_key=state.canvas_api_key)

    courses = service.get_user_courses()
    downloaded_files = service.download_course_files()
    
    all_assignments = []
    all_announcements = []

    for course in courses:
        assignments = service.get_course_assignments(course)
        announcements = service.get_course_announcements(course)
        
        all_assignments.extend([a.model_dump() for a in assignments])
        all_announcements.extend([ann.model_dump() for ann in announcements])

    # Retorna todas as informações para atualizar o Estado Global do LangGraph
    return {
        "courses": [course.model_dump() for course in courses],
        "downloaded_files": [file_meta.model_dump() for file_meta in downloaded_files],
        "assignments": all_assignments,
        "announcements": all_announcements
    }