from typing import List, Optional
from pydantic import BaseModel, Field

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
    downloaded_files: List[CanvasFileMetadata] = Field(default_factory=list)
    assignments: List[CanvasAssignment] = Field(default_factory=list)
    announcements: List[CanvasAnnouncement] = Field(default_factory=list)
    target_subject: Optional[str] = None
    generated_questions: List[dict] = Field(default_factory=list)