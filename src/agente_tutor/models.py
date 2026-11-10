from typing import List, Optional
from pydantic import BaseModel, Field

class TaskPriorityItem(BaseModel):
    course_id: int
    course_name: str
    title: str
    due_at: Optional[str] = None
    days_remaining: Optional[int] = None
    priority_level: str = Field(..., description="ALTA, MÉDIA ou BAIXA")
    action_recommendation: str = Field(..., description="Recomendação de ação (ex: Estudar cap 3, Entregar até amanhã)")

class CourseSummary(BaseModel):
    course_id: int
    course_name: str
    topic_title: str
    key_points: List[str] = Field(default_factory=list, description="Principais pontos extraídos do material")
    summary_text: str = Field(..., description="Resumo explicativo gerado pela LLM")
    sources_used: List[str] = Field(default_factory=list, description="Arquivos .md ou fontes utilizadas")

class TutorOutput(BaseModel):
    schedule: List[TaskPriorityItem] = Field(default_factory=list)
    summaries: List[CourseSummary] = Field(default_factory=list)