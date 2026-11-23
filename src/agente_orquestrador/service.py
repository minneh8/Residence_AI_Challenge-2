# src/agente_orquestrador/service.py
from pathlib import Path
from typing import List, Optional
from src.state import GlauxState
from src.agente_orquestrador.models import NodeName, OrchestratorPlan


class OrchestratorService:
    """
    Servico deterministico do Agente Orquestrador.
    Inspeciona o estado atual e o diretorio local (data/raw) para montar
    o plano minimo de execucao para cada botao acionado na interface.
    """

    def __init__(self, raw_dir: str = "data/raw"):
        self.raw_dir = Path(raw_dir)

    def resolve_course_id(self, state: GlauxState) -> Optional[int]:
        """
        Retorna o ID numerico da disciplina alvo.
        Se apenas target_subject foi informado, tenta localizar o ID em state.courses.
        """
        if state.curso_alvo is not None:
            return state.curso_alvo

        if state.target_subject and state.courses:
            termo = state.target_subject.strip().lower()
            for course in state.courses:
                c_name = course.name if hasattr(course, "name") else course.get("name", "")
                c_id = course.id if hasattr(course, "id") else course.get("id")
                if termo in c_name.lower():
                    return c_id

        return None

    def has_local_data(
        self,
        course_id: Optional[int] = None,
        require_pdfs: bool = False,
    ) -> bool:
        """
        Verifica se ha dados locais disponiveis em data/raw/.
        - require_pdfs=True: exige ao menos um arquivo .pdf (conteudo/ ou listas/).
        - require_pdfs=False: aceita tanto .pdf quanto assignments.json.
        """
        if not self.raw_dir.exists():
            return False

        def _folder_is_valid(folder: Path) -> bool:
            if not folder.is_dir():
                return False
            has_pdfs = any(
                p.is_file() and p.suffix.lower() == ".pdf"
                for p in folder.rglob("*")
            )
            if require_pdfs:
                return has_pdfs
            has_assignments = (folder / "assignments.json").exists()
            return has_pdfs or has_assignments

        if course_id is not None:
            return _folder_is_valid(self.raw_dir / str(course_id))

        for folder in self.raw_dir.iterdir():
            if folder.is_dir() and folder.name.isdigit() and _folder_is_valid(folder):
                return True

        return False

    def has_summary_in_state(
        self,
        state: GlauxState,
        course_id: Optional[int] = None,
    ) -> bool:
        """Verifica se ja existe resumo gerado em memoria no GlauxState."""
        if not state.summaries:
            return False
        if course_id is None:
            return True
        return any(s.get("course_id") == course_id for s in state.summaries)

    def build_execution_plan(self, state: GlauxState) -> OrchestratorPlan:
        """Define a sequencia minima de agentes para executar a acao solicitada."""
        resolved_id = self.resolve_course_id(state)
        steps: List[NodeName] = []

        match state.action:
            case "SINCRONIZAR_CANVAS":
                steps = ["canvas_agent"]
                reason = "Sincronizacao explicita com o Canvas LMS solicitada."

            case "GERAR_CRONOGRAMA":
                has_schedule_data = self.has_local_data(resolved_id, require_pdfs=False)
                if state.force_sync or not has_schedule_data:
                    steps = ["canvas_agent", "tutor_agent"]
                    reason = (
                        "Dados de tarefas ausentes ou sincronizacao forcada; "
                        "executando Canvas antes do Tutor."
                    )
                else:
                    steps = ["tutor_agent"]
                    reason = (
                        "Dados locais encontrados em data/raw; "
                        "pulando Canvas e acionando Tutor diretamente."
                    )

            case "GERAR_RESUMO":
                has_pdfs = self.has_local_data(resolved_id, require_pdfs=True)
                if state.force_sync or not has_pdfs:
                    steps = ["canvas_agent", "tutor_agent"]
                    reason = (
                        "PDFs ausentes em data/raw ou sincronizacao forcada; "
                        "baixando materiais antes de resumir."
                    )
                else:
                    steps = ["tutor_agent"]
                    reason = (
                        "PDFs ja disponiveis localmente; "
                        "acionando Tutor diretamente para sintese."
                    )

            case "GERAR_QUESTOES":
                has_pdfs = self.has_local_data(resolved_id, require_pdfs=True)
                has_summary = self.has_summary_in_state(state, resolved_id)

                if state.force_sync or not has_pdfs:
                    steps = ["canvas_agent", "tutor_agent", "question_generator_agent"]
                    reason = (
                        "Base de PDFs ausente ou sincronizacao forcada; "
                        "executando ingestao e sintese antes de gerar questoes."
                    )
                elif not has_summary:
                    steps = ["tutor_agent", "question_generator_agent"]
                    reason = (
                        "PDFs locais encontrados, mas sem resumo previo no estado; "
                        "acionando Tutor para preparar contexto antes do Gerador."
                    )
                else:
                    steps = ["question_generator_agent"]
                    reason = (
                        "Contexto e resumos prontos no estado; "
                        "acionando Agente Gerador diretamente."
                    )

            case "FLUXO_COMPLETO" | _:
                steps = ["canvas_agent", "tutor_agent"]
                reason = "Execucao completa da esteira padrao (Canvas -> Tutor)."

        return OrchestratorPlan(
            steps=steps,
            resolved_course_id=resolved_id,
            reason=reason,
        )