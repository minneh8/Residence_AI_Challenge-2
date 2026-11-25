# src/state.py
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

# Acoes estruturadas disparadas pelos botoes da interface web
ActionType = Literal[
    "SINCRONIZAR_CANVAS",   # Botao: Atualizar materias, PDFs, tarefas e avisos + indexar RAG
    "INDEXAR_RAG",          # Botao: Reindexar PDFs locais no ChromaDB
    "GERAR_CRONOGRAMA",     # Botao: Montar/atualizar apenas cronograma e prazos
    "GERAR_RESUMO",         # Botao: Gerar resumo didatico via RAG + Tutor
    "GERAR_QUESTOES",       # Botao: Gerar lista de exercicios via RAG + Gerador
    "FLUXO_COMPLETO",       # Botao: Executar esteira padrao completa
]


class CanvasCourse(BaseModel):
    id: int
    name: str
    course_code: Optional[str] = None


class CanvasFileMetadata(BaseModel):
    course_id: int
    filename: str
    url: Optional[str] = None
    category: Optional[str] = None


class CanvasAssignment(BaseModel):
    id: int
    course_id: int
    title: str
    description: Optional[str] = None
    due_at: Optional[str] = None
    points_possible: Optional[float] = None
    submitted: bool = False


class CanvasAnnouncement(BaseModel):
    id: int
    course_id: int
    title: str
    message: str
    posted_at: str


class GlauxState(BaseModel):
    """
    Estado global validado pelo Pydantic v2 compartilhado entre todos os nos do LangGraph.
    """

    # 1. Identificacao e credenciais
    user_id: str
    canvas_api_key: Optional[str] = None

    # 2. Comando recebido dos botoes da interface web
    action: ActionType = "FLUXO_COMPLETO"
    curso_alvo: Optional[int] = None
    target_subject: Optional[str] = None
    force_sync: bool = False

    # 3. Controle de fluxo do Agente Orquestrador
    execution_plan: List[str] = Field(default_factory=list)
    next_node: Optional[str] = None
    plan_initialized: bool = False
    rag_indexed_courses: List[int] = Field(default_factory=list)
    orchestrator_logs: List[str] = Field(default_factory=list)

    # 4. Dados produzidos pelos agentes especialistas
    courses: List[CanvasCourse] = Field(default_factory=list)
    low_grade_courses: List[str] = Field(default_factory=list)
    downloaded_files: List[Any] = Field(default_factory=list)
    assignments: List[Dict[str, Any]] = Field(default_factory=list)
    announcements: List[CanvasAnnouncement] = Field(default_factory=list)
    summaries: List[Dict[str, Any]] = Field(default_factory=list)
    generated_questions: List[Dict[str, Any]] = Field(default_factory=list)
    target_subject: Optional[str] = None
    # Opções da linha de comando (ver src/graph.py).
    tema: Optional[str] = None            # --tema: consulta única do Tutor
    curso_alvo: Optional[int] = None      # --curso: restringe a esteira a um curso
    quantidade_questoes: Optional[int] = None  # --questoes: quantas questões gerar
    generated_questions: List[dict] = Field(default_factory=list)
    generation_status: Optional[str] = None  # "ok", "sem_material" ou "erro"
    generation_message: Optional[str] = None  # mensagem para o aluno quando não há questões
