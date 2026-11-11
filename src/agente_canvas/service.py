# src/agente_canvas/service.py
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

import requests
from canvasapi import Canvas
from canvasapi.exceptions import CanvasException, InvalidAccessToken, Unauthorized

from src.state import CanvasCourse

# URL padrão quando CANVAS_API_URL não está definida no .env.
CANVAS_API_URL_PADRAO = "https://canvas.instructure.com"

# Mensagem única para token ausente ou inválido (401).
MSG_TOKEN_INVALIDO = (
    "Token do Canvas ausente ou inválido. Confira CANVAS_API_KEY no .env"
)

# Esperas (em segundos) entre as retentativas quando o Canvas está indisponível
# (503/rede): 1 tentativa inicial + 3 retentativas, aguardando 2, 5 e 10 s.
ESPERAS_RETENTATIVA = (2, 5, 10)

# 401: token ausente ou inválido. Erros de autenticação do canvasapi.
_ERROS_AUTENTICACAO = (InvalidAccessToken, Unauthorized)

# Caracteres inválidos em nomes de arquivo no Windows (e de controle).
_CARACTERES_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class CanvasAuthError(Exception):
    """Token do Canvas ausente ou inválido (401). Encerra sem modo offline."""


class CanvasUnavailableError(Exception):
    """Canvas indisponível (503/rede) após as retentativas. Aciona o modo offline."""


def _nome_seguro(nome: str) -> str:
    """Remove caracteres inválidos de um nome de arquivo, preservando o resto."""
    limpo = _CARACTERES_INVALIDOS.sub("_", nome).strip().strip(".")
    return limpo or "arquivo.pdf"


class CanvasService:
    def __init__(
        self,
        api_url: str = None,
        api_key: str = None,
        raw_dir: str = "data/raw",
        processed_dir: str = "data/processed",
    ):
        self.api_url = (
            api_url or os.getenv("CANVAS_API_URL") or CANVAS_API_URL_PADRAO
        ).rstrip("/")
        self.api_key = api_key or os.getenv("CANVAS_API_KEY")
        self.raw_dir = Path(raw_dir)
        self.processed_dir = Path(processed_dir)

        if not self.api_key:
            raise CanvasAuthError(MSG_TOKEN_INVALIDO)

        dominio = urlparse(self.api_url).netloc or self.api_url
        print(f" [Canvas] Conectando a {dominio}")
        self.canvas = Canvas(self.api_url, self.api_key)

    # --------------------------------------------------------------------------
    # Retentativas e validação do token
    # --------------------------------------------------------------------------
    def _com_retentativas(self, operacao, descricao: str):
        """Executa `operacao`, convertendo falhas do Canvas em erros tratáveis.

        401/token ausente -> CanvasAuthError (sem modo offline).
        503/rede -> até 3 retentativas (esperando 2, 5 e 10 s) e, se persistir,
        CanvasUnavailableError (que o nó traduz em modo offline).
        """
        tentativa = 0
        while True:
            try:
                return operacao()
            except _ERROS_AUTENTICACAO as e:
                raise CanvasAuthError(MSG_TOKEN_INVALIDO) from e
            except (CanvasException, requests.exceptions.RequestException) as e:
                if tentativa >= len(ESPERAS_RETENTATIVA):
                    raise CanvasUnavailableError(
                        f"Canvas indisponível ao {descricao} após "
                        f"{tentativa + 1} tentativas: {e}"
                    ) from e
                espera = ESPERAS_RETENTATIVA[tentativa]
                print(
                    f" [Canvas] Falha ao {descricao} ({e}); "
                    f"nova tentativa em {espera}s..."
                )
                time.sleep(espera)
                tentativa += 1

    def validar_token(self):
        """Confere o token em /users/self antes de qualquer outra chamada."""
        usuario = self._com_retentativas(
            self.canvas.get_current_user, "validar o token em /users/self"
        )
        nome = getattr(usuario, "name", "usuário")
        print(f" [Canvas] Token válido. Autenticado como: {nome}")
        return usuario

    def get_user_courses(self) -> List[CanvasCourse]:
        """Busca matérias ativas do usuário, removendo canais institucionais,
        duplicatas e canceladas. Valida o token antes de buscar."""
        self.validar_token()

        courses = self._com_retentativas(
            lambda: list(self.canvas.get_courses(enrollment_state="active")),
            "buscar os cursos",
        )

        valid_courses: List[CanvasCourse] = []
        seen_course_ids = set()
        seen_course_names = set()

        IGNORED_KEYWORDS = [
            "canal", "atualização", "atualizacao", "conectaref",
            "comunidade", "orientações", "orientacoes", "cancelado", "cancelada",
        ]

        for c in courses:
            course_name = getattr(c, "name", "").strip()
            name_lower = course_name.lower()
            course_id = getattr(c, "id", None)

            if not course_name or not course_id:
                continue
            if any(keyword in name_lower for keyword in IGNORED_KEYWORDS):
                continue
            if course_id in seen_course_ids or course_name in seen_course_names:
                continue

            seen_course_ids.add(course_id)
            seen_course_names.add(course_name)
            valid_courses.append(CanvasCourse(id=course_id, name=course_name))

        return valid_courses

    # --------------------------------------------------------------------------
    # Download de tarefas e PDFs
    # --------------------------------------------------------------------------
    def fetch_and_save_course_data(self, course_id: int) -> Dict[str, List[str]]:
        """Baixa tarefas e PDFs do curso no Canvas.

        Salva assignments.json (incluindo description) e os PDFs em
        data/raw/<course_id>/. Cada arquivo é tratado isoladamente: nomes
        inválidos são limpos, arquivos já existentes são pulados e o download
        vai para um .part que só é renomeado ao terminar.

        A conversão de PDF -> Markdown foi desativada de propósito: o Tutor usa
        a busca vetorial (src.rag.buscar), não os arquivos .md.

        Returns:
            {"baixados": [paths], "pulados": [paths]}.
        """
        course = self.canvas.get_course(course_id)
        course_folder = self.raw_dir / str(course_id)
        course_folder.mkdir(parents=True, exist_ok=True)
        baixados: List[str] = []
        pulados: List[str] = []

        # 1. Tarefas (com description, usada depois pelo Tutor)
        assignments = course.get_assignments()
        assignments_data = [
            {
                "id": a.id,
                "name": getattr(a, "name", ""),
                "description": getattr(a, "description", None),
                "due_at": getattr(a, "due_at", None),
                "submitted": getattr(a, "has_submitted_submissions", False),
            }
            for a in assignments
        ]
        with open(course_folder / "assignments.json", "w", encoding="utf-8") as f:
            json.dump(assignments_data, f, ensure_ascii=False, indent=2)

        # 2. Arquivos (PDFs)
        try:
            files = list(course.get_files())
        except Exception as e:
            print(f" [Canvas] Aviso ao listar arquivos do curso {course_id}: {e}")
            files = []

        for file in files:
            parcial = None
            try:
                nome_bruto = getattr(file, "display_name", None) or file.filename
                if not nome_bruto.lower().endswith(".pdf"):
                    continue

                nome = _nome_seguro(nome_bruto)
                destino = course_folder / nome

                if destino.exists():
                    pulados.append(str(destino))
                    print(f" [Canvas] PDF já existe, pulando: {nome}")
                    continue

                parcial = destino.with_suffix(destino.suffix + ".part")
                file.download(str(parcial))
                parcial.replace(destino)
                baixados.append(str(destino))
                print(f" [Canvas] PDF baixado: {nome}")
            except Exception as e:
                print(f" [Canvas] Erro ao baixar arquivo do curso {course_id}: {e}")
                if parcial is not None and parcial.exists():
                    try:
                        parcial.unlink()
                    except OSError:
                        pass

        return {"baixados": baixados, "pulados": pulados}
