# src/state.py
from typing import List, Optional
from pydantic import BaseModel, Field

class CanvasFileMetadata(BaseModel):
    course_id: int
    filename: str
    url: str

class CanvasCourse(BaseModel):
    id: int
    name: str

class GlauxState(BaseModel):
    
    user_id: str
    canvas_api_key: Optional[str] = None
    
    # Dados extraídos do Canvas LMS
    courses: List[CanvasCourse] = Field(default_factory=list)
    low_grade_courses: List[str] = Field(default_factory=list)
    downloaded_files: List[CanvasFileMetadata] = Field(default_factory=list)
    
    # Dados do Agente Gerador
    target_subject: Optional[str] = None
    generated_questions: List[dict] = Field(default_factory=list)