# src/agente_tutor/service.py
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone

# Força inclusão do PYTHONPATH
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq
from prompts.agente_tutor_prompts import TUTOR_SYSTEM_PROMPT
from src.rag import buscar
from src.state import CanvasCourse
from src.agente_tutor.models import TaskPriorityItem, CourseSummary

# Limite de caracteres da consulta montada a partir de título + descrição.
MAX_CARACTERES_CONSULTA = 300

# Trechos recuperados por consulta.
K_BUSCA = 3

_TAGS_HTML = re.compile(r"<[^>]+>")
_ESPACOS = re.compile(r"\s+")


def _remover_html(texto: Optional[str]) -> str:
    """Remove tags HTML e normaliza espaços (descrições do Canvas vêm em HTML)."""
    if not texto:
        return ""
    return _ESPACOS.sub(" ", html.unescape(_TAGS_HTML.sub(" ", texto))).strip()


class TutorService:
    def __init__(
        self,
        raw_dir: str = "data/raw",
        processed_dir: str = "data/processed",
        model_name: str = "openai/gpt-oss-20b",
        temperature: float = 0.0,
    ):
        self.raw_dir = Path(raw_dir)
        self.processed_dir = Path(processed_dir)
        self.model_name = model_name
        self.temperature = temperature
        self._api_key = os.getenv("GROQ_API_KEY")
        self._llm = None  # criada sob demanda: o caminho sem índice não usa LLM

    def _obter_llm(self) -> ChatGroq:
        """Instancia a LLM da Groq só quando há de fato uma chamada ao modelo."""
        if self._llm is None:
            if not self._api_key:
                print(" AVISO: GROQ_API_KEY não encontrada no .env. A chamada de LLM pode falhar.")
            self._llm = ChatGroq(
                model_name=self.model_name,
                temperature=self.temperature,
                groq_api_key=self._api_key,
            )
        return self._llm

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

                schedule_items.append(
                    TaskPriorityItem(
                        course_id=course.id,
                        course_name=course.name,
                        title=assign.get("title", assign.get("name", "Tarefa sem título")),
                        description=assign.get("description"),
                        due_at=due_at_str,
                        days_remaining=days_rem,
                        priority_level=priority,
                        action_recommendation=recommendation,
                    )
                )

        schedule_items.sort(key=lambda x: (x.days_remaining is None, x.days_remaining))
        return schedule_items

    # --------------------------------------------------------------------------
    # 2. CAMADA DE CONTEXTO (via RAG / buscar)
    # --------------------------------------------------------------------------
    def _consulta_da_tarefa(self, tarefa: TaskPriorityItem) -> str:
        """Monta a consulta de uma tarefa: título + descrição sem HTML, até 300 chars."""
        titulo = (tarefa.title or "").strip()
        descricao = _remover_html(tarefa.description)
        return f"{titulo} {descricao}".strip()[:MAX_CARACTERES_CONSULTA]

    def _recuperar_trechos(self, course_id: int, consultas: List[str]) -> List[Dict]:
        """Busca cada consulta, junta sem repetir (arquivo, página) e ordena por score.

        Consultas vazias são ignoradas; ValueError de buscar() é tratado.
        """
        por_pagina: Dict[tuple, Dict] = {}
        for consulta in consultas:
            if not consulta or not consulta.strip():
                continue
            try:
                resultados = buscar(consulta, course_id, k=K_BUSCA)
            except ValueError:
                continue
            for r in resultados:
                chave = (r["arquivo"], r["pagina"])
                if chave not in por_pagina or r["score"] > por_pagina[chave]["score"]:
                    por_pagina[chave] = r
        return sorted(por_pagina.values(), key=lambda r: r["score"], reverse=True)

    # --------------------------------------------------------------------------
    # 3. GERAÇÃO DE RESUMOS COM GROQ (baseada no material recuperado)
    # --------------------------------------------------------------------------
    def generate_summary_for_course(
        self,
        course_id: int,
        course_name: str,
        tarefas: Optional[List[TaskPriorityItem]] = None,
        tema: Optional[str] = None,
    ) -> CourseSummary:
        """Gera um resumo citável da disciplina a partir dos trechos recuperados.

        A consulta ao RAG vem, nesta ordem de prioridade:
          - de `tema`, quando informado (consulta única);
          - das 3 próximas tarefas pendentes (título + descrição sem HTML);
          - do nome do curso, quando não há tarefas.

        Se buscar() não retornar nada (curso não indexado), devolve uma mensagem
        e NÃO chama o LLM.
        """
        tarefas = tarefas or []

        if tema and tema.strip():
            consultas = [tema.strip()]
            foco = tema.strip()
            topic_title = f"Tema: {tema.strip()}"
        elif tarefas:
            consultas = [self._consulta_da_tarefa(t) for t in tarefas[:3]]
            consultas = [c for c in consultas if c]
            foco = "; ".join(t.title for t in tarefas[:3])
            topic_title = "Próximas tarefas pendentes"
            if not consultas:  # tarefas sem título/descrição úteis
                consultas = [course_name]
                foco = course_name
        else:
            consultas = [course_name]
            foco = course_name
            topic_title = f"Visão geral: {course_name}"

        trechos = self._recuperar_trechos(course_id, consultas)

        if not trechos:
            return CourseSummary(
                course_id=course_id,
                course_name=course_name,
                topic_title="Matéria não indexada",
                key_points=[],
                summary_text=(
                    f"A matéria '{course_name}' (curso {course_id}) não está indexada "
                    "no RAG. Rode a indexação (scripts/indexar.py) antes de gerar o resumo."
                ),
                sources_used=[],
            )

        contexto = "\n\n".join(
            f"[{r['arquivo']}, p.{r['pagina']}-{r['pagina_fim']}] {r['texto']}"
            for r in trechos
        )
        fontes = [
            {"arquivo": r["arquivo"], "pagina": r["pagina"], "pagina_fim": r["pagina_fim"]}
            for r in trechos
        ]

        messages = [
            SystemMessage(content=TUTOR_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Disciplina: {course_name}\n"
                    f"Foco do estudo: {foco}\n\n"
                    "Trechos do material (use APENAS estes e cite a fonte de cada "
                    f"afirmação):\n{contexto}\n\n"
                    "Gere o resumo seguindo exatamente as regras e a estrutura do sistema."
                )
            ),
        ]

        response = self._obter_llm().invoke(messages)

        return CourseSummary(
            course_id=course_id,
            course_name=course_name,
            topic_title=topic_title,
            key_points=[],
            summary_text=response.content,
            sources_used=fontes,
        )
