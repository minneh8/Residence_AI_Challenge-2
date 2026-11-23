# src/agente_canvas/service.py
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

import fitz
import requests
from canvasapi import Canvas
from canvasapi.exceptions import CanvasException, InvalidAccessToken, Unauthorized

from src.agente_canvas.classificador import classificar
from src.state import CanvasCourse

# Mensagem única para token ausente ou inválido (401).
MSG_TOKEN_INVALIDO = (
    "Token do Canvas ausente ou invalido. Confira CANVAS_API_KEY no .env"
)

# Não há URL padrão: canvas.instructure.com não é a instância da instituição e
# responde 503, o que caía no modo offline sem explicar a causa.
MSG_URL_AUSENTE = (
    "CANVAS_API_URL não definido. Informe no .env a URL da instituição "
    "(ex.: https://<instituicao>.instructure.com)"
)

# Esperas (em segundos) entre as retentativas quando o Canvas está indisponível
# (503/rede): 1 tentativa inicial + 3 retentativas, aguardando 2, 5 e 10 s.
ESPERAS_RETENTATIVA = (2, 5, 10)
_ERROS_AUTENTICACAO = (InvalidAccessToken, Unauthorized)
_CARACTERES_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Categorias retornadas pelo classificador.py que vao para a subpasta 'listas/'
CATEGORIAS_LISTAS = {"listas", "trabalho"}


class CanvasAuthError(Exception):
    """Token do Canvas ausente ou invalido (401). Encerra sem modo offline."""


class CanvasConfigError(CanvasAuthError):
    """Configuração do Canvas ausente (ex.: CANVAS_API_URL). Encerra sem modo
    offline, pelo mesmo caminho do erro de token."""


class CanvasUnavailableError(Exception):
    """Canvas indisponivel (503/rede) apos as retentativas. Aciona o modo offline."""


def _normalizar(texto: str) -> str:
    """Minusculas e sem acentos, para comparar nomes de forma robusta."""
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = sem_acento.encode("ascii", "ignore").decode("ascii")
    return sem_acento.lower().strip()


def _nome_seguro(nome: str) -> str:
    """Remove caracteres invalidos de um nome de arquivo, preservando o resto."""
    limpo = _CARACTERES_INVALIDOS.sub("_", nome).strip().strip(".")
    return limpo or "arquivo.pdf"


def _contar_paginas_pdf(caminho_pdf: Path) -> Optional[int]:
    """Retorna o numero de paginas do PDF para alimentar a regra paginas>100."""
    try:
        with fitz.open(str(caminho_pdf)) as doc:
            return len(doc)
    except Exception:
        return None


class CanvasService:
    def __init__(
        self,
        api_url: str = None,
        api_key: str = None,
        raw_dir: str = "data/raw",
    ):
        self.api_url = (api_url or os.getenv("CANVAS_API_URL") or "").strip().rstrip("/")
        self.api_key = api_key or os.getenv("CANVAS_API_KEY")
        self.raw_dir = Path(raw_dir)

        if not self.api_url:
            raise CanvasConfigError(MSG_URL_AUSENTE)
        if not self.api_key:
            raise CanvasAuthError(MSG_TOKEN_INVALIDO)

        dominio = urlparse(self.api_url).netloc or self.api_url
        print(f" [Canvas] Conectando a {dominio}")
        self.canvas = Canvas(self.api_url, self.api_key)

    def _com_retentativas(self, operacao, descricao: str):
        tentativa = 0
        while True:
            try:
                return operacao()
            except _ERROS_AUTENTICACAO as e:
                raise CanvasAuthError(MSG_TOKEN_INVALIDO) from e
            except (CanvasException, requests.exceptions.RequestException) as e:
                if tentativa >= len(ESPERAS_RETENTATIVA):
                    raise CanvasUnavailableError(
                        f"Canvas indisponivel ao {descricao} apos "
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
        usuario = self._com_retentativas(
            self.canvas.get_current_user, "validar o token em /users/self"
        )
        nome = getattr(usuario, "name", "usuario")
        print(f" [Canvas] Token valido. Autenticado como: {nome}")
        return usuario

    def get_user_courses(self) -> List[CanvasCourse]:
        self.validar_token()

        courses = self._com_retentativas(
            lambda: list(self.canvas.get_courses(enrollment_state="active")),
            "buscar os cursos",
        )

        valid_courses: List[CanvasCourse] = []
        seen_course_ids = set()
        seen_course_names = set()

        IGNORED_KEYWORDS = [
            "canal",
            "atualizacao",
            "conectaref",
            "comunidade",
            "orientacoes",
            "cancelado",
            "cancelada",
            "profoco",
        ]

        for c in courses:
            course_name = getattr(c, "name", "").strip()
            name_norm = _normalizar(course_name)
            course_id = getattr(c, "id", None)

            if not course_name or not course_id:
                continue
            if any(keyword in name_norm for keyword in IGNORED_KEYWORDS):
                continue
            if course_id in seen_course_ids or course_name in seen_course_names:
                continue

            seen_course_ids.add(course_id)
            seen_course_names.add(course_name)
            valid_courses.append(CanvasCourse(id=course_id, name=course_name))

        return valid_courses

    def _mapear_modulos_arquivos(self, course) -> Dict[int, str]:
        """Mapeia {file_id: nome_do_modulo} para enriquecer a classificacao."""
        mapa: Dict[int, str] = {}
        try:
            for modulo in course.get_modules(include=["items"]):
                nome_modulo = getattr(modulo, "name", None)
                if not nome_modulo:
                    continue
                for item in getattr(modulo, "items", []):
                    if item.get("type") == "File" and item.get("content_id"):
                        mapa[int(item["content_id"])] = nome_modulo
        except Exception:
            pass
        return mapa

    def _classificar_e_mover_pdf(
        self,
        arquivo_origem: Path,
        course_folder: Path,
        nome_final: str,
        nome_modulo: Optional[str] = None,
    ) -> Path:
        """
        Recebe um PDF (seja recem-baixado .part ou ja existente na pasta da materia),
        classifica pelo classificador.py e move para conteudo/ ou listas/.
        """
        pasta_conteudo = course_folder / "conteudo"
        pasta_listas = course_folder / "listas"
        pasta_conteudo.mkdir(parents=True, exist_ok=True)
        pasta_listas.mkdir(parents=True, exist_ok=True)

        tamanho_bytes = arquivo_origem.stat().st_size
        paginas = _contar_paginas_pdf(arquivo_origem)

        categoria, origem = classificar(
            nome=nome_final,
            modulo=nome_modulo,
            tamanho=tamanho_bytes,
            paginas=paginas,
        )

        subpasta = pasta_listas if categoria in CATEGORIAS_LISTAS else pasta_conteudo
        destino = subpasta / nome_final

        if arquivo_origem.resolve() != destino.resolve():
            shutil.move(str(arquivo_origem), str(destino))

        print(
            f" [Canvas] PDF classificado [{categoria} | {origem}]: "
            f"{course_folder.name}/{subpasta.name}/{nome_final}"
        )
        return destino

    def organizar_pdfs_existentes(self, course_id: Optional[int] = None) -> int:
        """
        Varre data/raw/ (ou apenas o course_id especificado) e move qualquer PDF
        que ainda esteja solto na raiz da disciplina para conteudo/ ou listas/.
        """
        if not self.raw_dir.exists():
            return 0

        if course_id is not None:
            pastas = [self.raw_dir / str(course_id)]
        else:
            pastas = [p for p in self.raw_dir.iterdir() if p.is_dir() and p.name.isdigit()]

        total_movidos = 0
        for course_folder in pastas:
            if not course_folder.is_dir():
                continue

            pdfs_soltos = [
                f for f in course_folder.iterdir()
                if f.is_file() and f.suffix.lower() == ".pdf"
            ]
            for pdf in pdfs_soltos:
                nome_limpo = _nome_seguro(pdf.name)
                self._classificar_e_mover_pdf(
                    arquivo_origem=pdf,
                    course_folder=course_folder,
                    nome_final=nome_limpo,
                )
                total_movidos += 1

        return total_movidos

    def fetch_and_save_course_data(self, course_id: int) -> Dict[str, List[str]]:
        """
        Organiza PDFs locais ja existentes da disciplina, baixa os novos PDFs do Canvas
        (do mais recente para o mais antigo com Early Stop) e direciona cada um para
        data/raw/<course_id>/conteudo/ ou data/raw/<course_id>/listas/.
        """
        course_folder = self.raw_dir / str(course_id)
        pasta_conteudo = course_folder / "conteudo"
        pasta_listas = course_folder / "listas"

        course_folder.mkdir(parents=True, exist_ok=True)
        pasta_conteudo.mkdir(parents=True, exist_ok=True)
        pasta_listas.mkdir(parents=True, exist_ok=True)

        # Primeiro organiza qualquer PDF que ja estivesse solto na raiz desta materia
        self.organizar_pdfs_existentes(course_id=course_id)

        course = self.canvas.get_course(course_id)
        baixados: List[str] = []
        pulados: List[str] = []

        # 1. Tarefas
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

        # 2. Mapeia modulos para dar contexto ao classificador
        mapa_modulos = self._mapear_modulos_arquivos(course)

        # 3. Arquivos (PDFs) ordenados do mais recente para o mais antigo
        try:
            files = list(course.get_files(sort="created_at", order="desc"))
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
                ja_existe = (
                    (pasta_conteudo / nome).exists()
                    or (pasta_listas / nome).exists()
                )

                if ja_existe:
                    pulados.append(nome)
                    print(f" [Canvas] PDF ja existe (Early Stop): {nome}")
                    break

                parcial = course_folder / f"{nome}.part"
                file.download(str(parcial))

                file_id = getattr(file, "id", None)
                nome_modulo = mapa_modulos.get(int(file_id)) if file_id else None

                destino = self._classificar_e_mover_pdf(
                    arquivo_origem=parcial,
                    course_folder=course_folder,
                    nome_final=nome,
                    nome_modulo=nome_modulo,
                )
                baixados.append(str(destino))
            except Exception as e:
                print(f" [Canvas] Erro ao baixar arquivo do curso {course_id}: {e}")
                if parcial is not None and parcial.exists():
                    try:
                        parcial.unlink()
                    except OSError:
                        pass

        return {"baixados": baixados, "pulados": pulados}