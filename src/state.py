from typing import List, Optional
from pydantic import BaseModel, Field

from src.agente_tutor.models import CourseSummary, TaskPriorityItem

class CanvasCourse(BaseModel):
    id: int
    name: str

class CanvasAssignment(BaseModel):
    id: int
    course_id: int
    title: str
    description: Optional[str] = None
    due_at: Optional[str] = None  # data e hora limite das tarefas
    points_possible: Optional[float] = None
    submitted: bool = False

class CanvasAnnouncement(BaseModel):
    id: int
    course_id: int
    title: str
    message: str
    posted_at: str


class CanvasFileMetadata(BaseModel):
    course_id: int
    filename: str
    url: str

class GlauxState(BaseModel):
    user_id: str
    canvas_api_key: Optional[str] = None
    courses: List[CanvasCourse] = Field(default_factory=list)
    low_grade_courses: List[str] = Field(default_factory=list)
    downloaded_files: List[str] = Field(default_factory=list)
    assignments: List[TaskPriorityItem] = Field(default_factory=list)
    summaries: List[CourseSummary] = Field(default_factory=list)
    announcements: List[CanvasAnnouncement] = Field(default_factory=list)
    target_subject: Optional[str] = None
    # Opções da linha de comando (ver src/graph.py).
    tema: Optional[str] = None            # --tema: consulta única do Tutor
    curso_alvo: Optional[int] = None      # --curso: restringe a esteira a um curso
    sync_completo: bool = False           # --completo: ignora a parada antecipada do Canvas
    quantidade_questoes: Optional[int] = None  # --questoes: quantas questões gerar
    generated_questions: List[dict] = Field(default_factory=list)
    generation_status: Optional[str] = None  # "ok", "sem_material" ou "erro"
    generation_message: Optional[str] = None  # mensagem para o aluno quando não há questões
