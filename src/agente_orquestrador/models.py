# src/agente_orquestrador/models.py
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

NodeName = Literal[
    "canvas_agent",
    "rag_index_node",
    "tutor_agent",
    "question_generator_agent",
    "END",
]


class OrchestratorPlan(BaseModel):
    """Contrato estruturado do plano de execucao montado pelo Orquestrador."""

    steps: List[NodeName] = Field(
        default_factory=list,
        description="Sequencia ordenada de nos a serem executados.",
    )
    resolved_course_id: Optional[int] = Field(
        None,
        description="ID da disciplina alvo resolvido a partir de curso_alvo ou target_subject.",
    )
    reason: str = Field(
        ...,
        description="Justificativa tecnica da rota escolhida.",
    )