# src/agente_orquestrador/models.py
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

# Nomes exatos dos nos registrados no StateGraph (src/graph.py)
NodeName = Literal[
    "canvas_agent",
    "tutor_agent",
    "question_generator_agent",
    "END",
]


class OrchestratorPlan(BaseModel):
    """
    Contrato estruturado retornado pelo OrchestratorService ao analisar uma requisicao.
    """

    steps: List[NodeName] = Field(
        default_factory=list,
        description="Fila ordenada de nos que serao executados em sequencia.",
    )
    resolved_course_id: Optional[int] = Field(
        None,
        description="ID da disciplina alvo resolvido a partir de curso_alvo ou target_subject.",
    )
    reason: str = Field(
        ...,
        description="Justificativa tecnica da rota escolhida pelo orquestrador.",
    )