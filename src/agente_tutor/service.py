# src/agente_tutor/service.py
import os
import sys
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

# Força inclusão do PYTHONPATH
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq  # 👈 Import do Groq via LangChain
from prompts.agente_tutor_prompts import TUTOR_SYSTEM_PROMPT
from src.state import CanvasCourse
from src.agente_tutor.models import TaskPriorityItem, CourseSummary, TutorOutput


class TutorService:
    def __init__(
        self,
        raw_dir: str = "data/raw",
        processed_dir: str = "data/processed",
        model_name: str = "openai/gpt-oss-20b",  
        temperature: float = 0.3
    ):
        self.raw_dir = Path(raw_dir)
        self.processed_dir = Path(processed_dir)
        
        # Puxa a chave GROQ_API_KEY do arquivo .env
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            print(" AVISO: GROQ_API_KEY não encontrada no .env. As chamadas de LLM poderão falhar.")
        
        # Inicializa a LLM da Groq
        self.llm = ChatGroq(
            model_name=model_name,
            temperature=temperature,
            groq_api_key=api_key
        )

    # --------------------------------------------------------------------------
    # 1. CRONOGRAMA & TAREFAS
    # --------------------------------------------------------------------------
    def generate_schedule(self, courses: List[CanvasCourse]) -> List[TaskPriorityItem]:
        """Analisador de tarefas e prioridades com base nos prazos (apenas tarefas futuras)."""
        schedule_items: List[TaskPriorityItem] = []
        now = datetime.now(timezone.utc)

        for course in courses:
            assignments_file = self.raw_dir / str(course.id) / "assignments.json"
            if not assignments_file.exists():
                continue

            with open(assignments_file, "r", encoding="utf-8") as f:
                assignments = json.load(f)

            for assign in assignments:
                # 1. Ignora tarefas já submetidas/entregues
                if assign.get("submitted", False):
                    continue

                due_at_str = assign.get("due_at")
                days_rem = None
                priority = "BAIXA"
                recommendation = "Manter estudos regulares."

                if due_at_str:
                    try:
                        due_date = datetime.fromisoformat(due_at_str.replace("Z", "+00:00"))
                        days_rem = (due_date - now).days
                        
                        if days_rem < 0:
                            continue

                        if days_rem <= 2:
                            priority = "ALTA"
                            recommendation = "🔴 URGENTE: Foco total na entrega até o prazo."
                        elif days_rem <= 7:
                            priority = "MÉDIA"
                            recommendation = "🟡 ATENÇÃO: Adiantar tarefas desta semana."
                    except ValueError:
                        pass
                else:
                    # Opcional: Se a tarefa não tem data limite (due_at = None), decide se ignora ou mantém
                    pass

                schedule_items.append(
                    TaskPriorityItem(
                        course_id=course.id,
                        course_name=course.name,
                        title=assign.get("title", assign.get("name", "Tarefa sem título")),
                        due_at=due_at_str,
                        days_remaining=days_rem,
                        priority_level=priority,
                        action_recommendation=recommendation
                    )
                )

        # Ordena as tarefas mais urgentes primeiro
        schedule_items.sort(key=lambda x: (x.days_remaining is None, x.days_remaining))
        return schedule_items

    # --------------------------------------------------------------------------
    # 2. CAMADA DE CONTEXTO
    # --------------------------------------------------------------------------
    def _fetch_context(self, course_id: int) -> tuple[str, List[str]]:
        course_processed_folder = self.processed_dir / str(course_id)
        if not course_processed_folder.exists():
            return "Nenhum material em Markdown encontrado.", []

        md_files = list(course_processed_folder.glob("*.md"))
        if not md_files:
            return "Nenhum arquivo .md convertido.", []

        combined_text = ""
        sources = []

        for md_file in md_files[:3]:
            sources.append(md_file.name)
            with open(md_file, "r", encoding="utf-8") as f:
                combined_text += f"\n--- Fonte: {md_file.name} ---\n" + f.read()[:3000]

        return combined_text, sources

    # --------------------------------------------------------------------------
    # 3. GERAÇÃO DE RESUMOS COM GROQ
    # --------------------------------------------------------------------------
    def generate_summary_for_course(self, course_id: int, course_name: str) -> CourseSummary:
        context_text, sources = self._fetch_context(course_id)

        if not sources:
            return CourseSummary(
                course_id=course_id,
                course_name=course_name,
                topic_title="Sem Conteúdo Processado",
                key_points=["Nenhum PDF/MD disponível para esta disciplina."],
                summary_text="Não há materiais processados em data/processed/ para sintetizar.",
                sources_used=[]
            )

        messages = [
            SystemMessage(content=TUTOR_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Disciplina: {course_name}\n\n"
                    f"Material de Estudo:\n{context_text}\n\n"
                    "Por favor, gere o resumo de estudos seguindo a estrutura exata definida no sistema."
                )
            ),
        ]

        response = self.llm.invoke(messages)

        return CourseSummary(
            course_id=course_id,
            course_name=course_name,
            topic_title=f"Resumo Didático: {course_name}",
            key_points=["Resumo gerado com base no material processado em Markdown."],
            summary_text=response.content,
            sources_used=sources
        )