# src/agente_orquestrador/service.py
from pathlib import Path
from typing import List, Optional
from src.state import GlauxState
from src.agente_orquestrador.models import NodeName, OrchestratorPlan


class OrchestratorService:
    """
    Servico deterministico do Agente Orquestrador.
    Inspeciona o estado atual, os arquivos locais (data/raw) e o indice vetorial (ChromaDB)
    para montar o menor plano de execucao necessario para cada acao.
    """

    def __init__(self, raw_dir: str = "data/raw", chroma_dir: str = "data/chroma"):
        self.raw_dir = Path(raw_dir)
        self.chroma_dir = Path(chroma_dir)

    def resolve_course_id(self, state: GlauxState) -> Optional[int]:
        """Resolve o ID numerico da disciplina alvo a partir de curso_alvo ou target_subject."""
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
        require_content_pdfs: bool = False,
    ) -> bool:
        """
        Verifica se ha dados locais disponiveis em data/raw/.
        - require_content_pdfs=True: exige PDFs teoricos em conteudo/ (ou soltos na raiz).
        - require_content_pdfs=False: aceita qualquer PDF ou assignments.json.
        """
        if not self.raw_dir.exists():
            return False

        def _folder_is_valid(folder: Path) -> bool:
            if not folder.is_dir():
                return False

            if require_content_pdfs:
                pasta_conteudo = folder / "conteudo"
                if pasta_conteudo.is_dir() and any(
                    p.is_file() and p.suffix.lower() == ".pdf"
                    for p in pasta_conteudo.rglob("*")
                ):
                    return True
                return any(
                    p.is_file() and p.suffix.lower() == ".pdf"
                    for p in folder.iterdir()
                )

            has_any_pdf = any(
                p.is_file() and p.suffix.lower() == ".pdf"
                for p in folder.rglob("*")
            )
            has_assignments = (folder / "assignments.json").exists()
            return has_any_pdf or has_assignments

        if course_id is not None:
            return _folder_is_valid(self.raw_dir / str(course_id))

        for folder in self.raw_dir.iterdir():
            if folder.is_dir() and folder.name.isdigit() and _folder_is_valid(folder):
                return True

        return False

    def is_course_indexed_in_rag(self, course_id: Optional[int] = None) -> bool:
        """Verifica se a base vetorial do ChromaDB ja possui chunks indexados."""
        if not self.chroma_dir.exists():
            return False

        try:
            from src.rag.indexacao import obter_colecao

            colecao = obter_colecao(criar=False)
            if colecao is None:
                return False

            if course_id is not None:
                res = colecao.get(where={"course_id": course_id}, limit=1)
                return len(res.get("ids", [])) > 0

            return colecao.count() > 0
        except Exception:
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
        """Define a sequencia minima de nos para executar a acao solicitada."""
        resolved_id = self.resolve_course_id(state)
        steps: List[NodeName] = []

        match state.action:
            case "SINCRONIZAR_CANVAS":
                steps = ["canvas_agent", "rag_index_node"]
                reason = "Sincronizacao explicita com o Canvas LMS seguida de indexacao no RAG."

            case "INDEXAR_RAG":
                has_pdfs = self.has_local_data(resolved_id, require_content_pdfs=True)
                if not has_pdfs:
                    steps = ["canvas_agent", "rag_index_node"]
                    reason = "PDFs ausentes localmente; baixando do Canvas antes de indexar no RAG."
                else:
                    steps = ["rag_index_node"]
                    reason = "PDFs encontrados em data/raw; indexando base vetorial no ChromaDB."

            case "GERAR_CRONOGRAMA":
                has_schedule_data = self.has_local_data(resolved_id, require_content_pdfs=False)
                if state.force_sync or not has_schedule_data:
                    steps = ["canvas_agent", "tutor_agent"]
                    reason = (
                        "Dados de tarefas ausentes ou sincronizacao forcada; "
                        "executando Canvas antes do Tutor."
                    )
                else:
                    steps = ["tutor_agent"]
                    reason = (
                        "Dados locais de tarefas encontrados; "
                        "acionando Tutor diretamente para cronograma."
                    )

            case "GERAR_RESUMO":
                has_pdfs = self.has_local_data(resolved_id, require_content_pdfs=True)
                is_indexed = self.is_course_indexed_in_rag(resolved_id)

                if state.force_sync or not has_pdfs:
                    steps = ["canvas_agent", "rag_index_node", "tutor_agent"]
                    reason = (
                        "PDFs ausentes ou sincronizacao forcada; "
                        "baixando materiais, indexando no RAG e acionando o Tutor."
                    )
                elif not is_indexed:
                    steps = ["rag_index_node", "tutor_agent"]
                    reason = (
                        "PDFs locais encontrados, mas ainda nao indexados no ChromaDB; "
                        "indexando no RAG antes de resumir."
                    )
                else:
                    steps = ["tutor_agent"]
                    reason = (
                        "Base vetorial RAG ja indexada para a disciplina; "
                        "acionando Tutor diretamente."
                    )

            case "GERAR_QUESTOES":
                has_pdfs = self.has_local_data(resolved_id, require_content_pdfs=True)
                is_indexed = self.is_course_indexed_in_rag(resolved_id)
                has_summary = self.has_summary_in_state(state, resolved_id)

                if state.force_sync or not has_pdfs:
                    steps = ["canvas_agent", "rag_index_node", "tutor_agent", "question_generator_agent"]
                    reason = (
                        "PDFs ausentes ou sincronizacao forcada; "
                        "executando ingestao, indexacao RAG e sintese antes de gerar questoes."
                    )
                elif not is_indexed:
                    steps = ["rag_index_node", "tutor_agent", "question_generator_agent"]
                    reason = (
                        "Indexando PDFs no ChromaDB e preparando topicos antes do Gerador."
                    )
                elif not has_summary:
                    steps = ["tutor_agent", "question_generator_agent"]
                    reason = (
                        "RAG pronto; acionando Tutor para mapear topicos antes do Gerador."
                    )
                else:
                    steps = ["question_generator_agent"]
                    reason = (
                        "RAG e resumos prontos; acionando Agente Gerador diretamente."
                    )

            case "FLUXO_COMPLETO" | _:
                steps = ["canvas_agent", "rag_index_node", "tutor_agent"]
                reason = "Execucao completa da esteira (Canvas -> Indexacao RAG -> Tutor)."

        return OrchestratorPlan(
            steps=steps,
            resolved_course_id=resolved_id,
            reason=reason,
        )