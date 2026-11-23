# src/agente_canvas/service.py
import logging
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

import pymupdf
import requests
from canvasapi import Canvas
from canvasapi.exceptions import CanvasException, InvalidAccessToken, Unauthorized

from src.agente_canvas.catalogo import (
    Catalogo,
    EstadoAluno,
    agora_iso,
    gravar_json_atomico,
    para_datetime,
)
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

# Categorias finais (pastas em data/raw/<course_id>/). "indefinido" das regras
# vai para a LLM e, se ela não decidir, vira "outros".
CATEGORIAS = ("slides", "listas", "trabalho", "livros", "outros")

# Pastas da organização anterior (origin/testes), migradas e removidas se vazias.
PASTAS_ANTIGAS = ("conteudo",)

logger = logging.getLogger(__name__)


class CanvasAuthError(Exception):
    """Token do Canvas ausente ou invalido (401). Encerra sem modo offline."""


class CanvasConfigError(CanvasAuthError):
    """Configuração do Canvas ausente (ex.: CANVAS_API_URL). Encerra sem modo
    offline, pelo mesmo caminho do erro de token."""


class CanvasUnavailableError(Exception):
    """Canvas indisponivel (503/rede) apos as retentativas. Aciona o modo offline."""


class LLMIndisponivel(Exception):
    """A LLM de classificação falhou (erro da API). O arquivo não entra no
    catálogo e o estado do aluno não avança, para tentar de novo na próxima
    sincronização."""


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
        with pymupdf.open(str(caminho_pdf)) as doc:
            return len(doc)
    except Exception:
        return None


class CanvasService:
    def __init__(
        self,
        api_url: str = None,
        api_key: str = None,
        raw_dir: str = "data/raw",
        state_dir: str = "data/canvas_state",
        classificador_llm=None,
    ):
        """
        Args:
            state_dir: pasta do estado de sincronização por aluno.
            classificador_llm: função (caminho, nome, modulo, paginas) -> dict,
                usada quando as regras devolvem "indefinido". Padrão:
                classificador_llm.classificar_llm (Groq). Os testes passam uma
                versão simulada.
        """
        self.api_url = (api_url or os.getenv("CANVAS_API_URL") or "").strip().rstrip("/")
        self.api_key = api_key or os.getenv("CANVAS_API_KEY")
        self.raw_dir = Path(raw_dir)
        self.state_dir = Path(state_dir)
        self.user_id: Optional[str] = None
        self.requisicoes = 0
        if classificador_llm is None:
            from src.agente_canvas.classificador_llm import classificar_llm
            classificador_llm = classificar_llm
        self.classificador_llm = classificador_llm

        if not self.api_url:
            raise CanvasConfigError(MSG_URL_AUSENTE)
        if not self.api_key:
            raise CanvasAuthError(MSG_TOKEN_INVALIDO)

        dominio = urlparse(self.api_url).netloc or self.api_url
        print(f" [Canvas] Conectando a {dominio}")
        self.canvas = Canvas(self.api_url, self.api_key)
        self._instalar_contador()

    def _instalar_contador(self) -> None:
        """Conta as respostas HTTP do Canvas (hook na sessão requests do canvasapi)."""
        def contar(resposta, *args, **kwargs):
            self.requisicoes += 1
            return resposta

        try:
            sessao = self.canvas._Canvas__requester._session
            sessao.hooks.setdefault("response", []).append(contar)
        except AttributeError:
            pass  # Canvas simulado nos testes

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
        # Id real do aluno: chave do estado em data/canvas_state/<user_id>.json.
        self.user_id = str(getattr(usuario, "id", "") or "desconhecido")
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

    def _iterar_paginado(self, fabrica, descricao: str):
        """Itera um PaginatedList item a item (página a página), com retentativas.

        `fabrica()` cria a listagem. Como o canvasapi só busca a próxima página
        quando a iteração chega nela, parar o loop (break) economiza as
        requisições das páginas seguintes. Se uma página falhar (503/rede), a
        listagem é recriada e os itens já entregues são pulados.
        """
        entregues = 0
        tentativa = 0
        while True:
            try:
                for i, item in enumerate(fabrica()):
                    if i < entregues:
                        continue
                    entregues += 1
                    yield item
                return
            except _ERROS_AUTENTICACAO as e:
                raise CanvasAuthError(MSG_TOKEN_INVALIDO) from e
            except (CanvasException, requests.exceptions.RequestException) as e:
                if tentativa >= len(ESPERAS_RETENTATIVA):
                    raise CanvasUnavailableError(
                        f"Canvas indisponivel ao {descricao} apos "
                        f"{tentativa + 1} tentativas: {e}"
                    ) from e
                espera = ESPERAS_RETENTATIVA[tentativa]
                print(f" [Canvas] Falha ao {descricao} ({e}); nova tentativa em {espera}s...")
                time.sleep(espera)
                tentativa += 1

    def _mapear_modulos_arquivos(self, course) -> Dict[int, str]:
        """Mapeia {file_id: nome_do_modulo} (uma busca por curso, include[]=items).

        Uma falha não interrompe a sincronização: fica registrada no log e os
        arquivos são classificados sem módulo.
        """
        mapa: Dict[int, str] = {}
        try:
            modulos = self._iterar_paginado(
                lambda: course.get_modules(include=["items"]),
                f"listar os módulos do curso {course.id}",
            )
            for modulo in modulos:
                nome_modulo = getattr(modulo, "name", None)
                if not nome_modulo:
                    continue
                for item in getattr(modulo, "items", None) or []:
                    if item.get("type") == "File" and item.get("content_id"):
                        mapa.setdefault(int(item["content_id"]), nome_modulo)
        except CanvasAuthError:
            raise
        except Exception as e:
            logger.warning("Curso %s: falha ao mapear módulos (%s); "
                           "classificando sem módulo.", getattr(course, "id", "?"), e)
            print(f" [Canvas] Aviso: módulos do curso indisponíveis ({e}); "
                  "classificando sem módulo.")
        return mapa

    # --------------------------------------------------------------------------
    # Sincronização incremental de um curso
    # --------------------------------------------------------------------------
    def sincronizar_curso(self, course_id: int, completo: bool = False) -> Dict:
        """Baixa só o que mudou nos PDFs do curso, classifica e registra no catálogo.

        Lista os arquivos com sort=updated_at&order=desc e para no primeiro com
        updated_at <= ultimo_updated_at do estado do aluno. Sem estado (ou com
        `completo=True`), percorre tudo. Arquivos do catálogo que sumiram do
        disco fazem a listagem continuar até que todos sejam baixados de novo.

        Para cada PDF:
          - mesmo id e updated_at no catálogo e arquivo no disco: só registra
            (outro aluno já baixou);
          - PDF já existente no disco e fora do catálogo (solto na raiz, em
            conteudo/ ou listas/) com o mesmo nome: migra para a pasta da
            categoria, sem baixar;
          - senão, baixa para um .part, conta as páginas, classifica (regras e,
            se indefinido, LLM) e move para data/raw/<id>/<categoria>/<nome>.
            Numa atualização com o mesmo nome, a categoria é mantida.

        O estado do aluno só é gravado se não houve nenhuma falha.

        Returns:
            Resumo com as listas novos, atualizados, recuperados, registrados,
            migrados, pulados, falhas, removidos, baixados (caminhos), além de
            categorias (contagem no catálogo), requisicoes, parou_em, mudou e
            estado_gravado.
        """
        requisicoes_antes = self.requisicoes
        if self.user_id is None:
            self.validar_token()

        pasta = self.raw_dir / str(course_id)
        pasta.mkdir(parents=True, exist_ok=True)
        catalogo = Catalogo(pasta)
        estado = EstadoAluno(self.state_dir, self.user_id)
        resumo = {
            "course_id": course_id,
            "novos": [], "atualizados": [], "recuperados": [], "registrados": [],
            "migrados": [], "pulados": [], "falhas": [], "removidos": [],
            "baixados": [], "pendentes_llm": [], "parou_em": None, "estado_gravado": False,
        }

        course = self._com_retentativas(
            lambda: self.canvas.get_course(course_id), f"abrir o curso {course_id}")
        self._salvar_assignments(course, pasta)
        modulos = self._mapear_modulos_arquivos(course)

        estado_curso = None if completo else estado.do_curso(course_id)
        limite = para_datetime((estado_curso or {}).get("ultimo_updated_at"))
        ausentes = catalogo.ids_ausentes_no_disco()
        # Migração só numa varredura completa (primeira sincronização do aluno ou
        # --completo): fora dela, PDFs soltos não forçam percorrer a lista toda.
        soltos = self._pdfs_soltos(pasta, catalogo)
        vistos = set()
        primeiro = None
        percorreu_tudo = True

        listagem = self._iterar_paginado(
            lambda: course.get_files(sort="updated_at", order="desc"),
            f"listar os arquivos do curso {course_id}",
        )
        for arquivo in listagem:
            fid = str(arquivo.id)
            vistos.add(fid)
            atualizado_em = getattr(arquivo, "updated_at", None)
            nome_canvas = getattr(arquivo, "display_name", None) or arquivo.filename
            if primeiro is None:
                primeiro = (atualizado_em, fid)

            dt = para_datetime(atualizado_em)
            abaixo_do_limite = limite is not None and dt is not None and dt <= limite
            if abaixo_do_limite:
                # Ids do catálogo sumidos do disco que ainda não passaram na lista.
                pendentes = ausentes - (vistos - {fid})
                if not pendentes:
                    resumo["parou_em"] = nome_canvas
                    percorreu_tudo = False
                    break
                if fid not in ausentes:
                    continue  # já sincronizado; só procurando os que sumiram do disco

            if not nome_canvas.lower().endswith(".pdf"):
                resumo["pulados"].append(nome_canvas)
                continue

            parcial = pasta / f".{fid}.part"
            try:
                self._tratar_pdf(arquivo, nome_canvas, atualizado_em, catalogo,
                                 modulos, soltos if limite is None else {}, resumo)
            except CanvasAuthError:
                raise
            except LLMIndisponivel as e:
                print(f" [Canvas] LLM indisponível para {nome_canvas} ({e}); "
                      "fica fora do catálogo e será tentado na próxima sincronização.")
                resumo["pendentes_llm"].append(nome_canvas)
            except Exception as e:
                logger.exception("Curso %s: falha no arquivo %s", course_id, nome_canvas)
                print(f" [Canvas] Erro no arquivo {nome_canvas}: {e}")
                resumo["falhas"].append(nome_canvas)
            finally:
                if parcial.exists():
                    try:
                        parcial.unlink()
                    except OSError:
                        pass

        # Numa varredura completa, ids do catálogo que sumiram do disco e não
        # existem mais no Canvas saem do catálogo.
        if percorreu_tudo:
            for fid in sorted(ausentes - vistos):
                entrada = catalogo.entradas.pop(fid)
                resumo["removidos"].append(entrada.get("nome"))
            if resumo["removidos"]:
                catalogo.salvar()
        self._remover_pastas_antigas_vazias(pasta)

        if soltos and limite is None:
            restantes = ", ".join(sorted(p.name for p in soltos.values()))
            print(f" [Canvas] {len(soltos)} PDF(s) local(is) sem correspondência no "
                  f"Canvas ficaram onde estavam: {restantes}")

        if not resumo["falhas"] and not resumo["pendentes_llm"]:
            ultimo = primeiro or (
                (estado_curso or {}).get("ultimo_updated_at"),
                (estado_curso or {}).get("ultimo_file_id"),
            )
            estado.gravar_curso(course_id, ultimo[0], ultimo[1])
            resumo["estado_gravado"] = True

        contagem: Dict[str, int] = {}
        for entrada in catalogo.entradas.values():
            contagem[entrada["categoria"]] = contagem.get(entrada["categoria"], 0) + 1
        resumo["categorias"] = dict(sorted(contagem.items()))
        resumo["requisicoes"] = self.requisicoes - requisicoes_antes
        resumo["mudou"] = any(resumo[k] for k in
                              ("novos", "atualizados", "recuperados", "migrados", "removidos"))
        return resumo

    def _tratar_pdf(self, arquivo, nome_canvas: str, atualizado_em, catalogo: Catalogo,
                    modulos: Dict[int, str], soltos: Dict[str, Path], resumo: Dict) -> None:
        """Decide entre registrar, migrar ou baixar um PDF da listagem."""
        fid = str(arquivo.id)
        nome = _nome_seguro(nome_canvas)
        entrada = catalogo.get(fid)
        no_disco = catalogo.existe_no_disco(entrada)

        # a. Já baixado (por este ou outro aluno) e sem mudança: só registra.
        if entrada and entrada.get("updated_at") == atualizado_em and no_disco:
            resumo["registrados"].append(nome_canvas)
            return

        modulo = modulos.get(int(arquivo.id))
        tamanho = getattr(arquivo, "size", None)

        # Migração: o PDF já está no disco fora do catálogo; registra sem baixar.
        if not no_disco and nome.lower() in soltos:
            origem_local = soltos.pop(nome.lower())
            paginas = _contar_paginas_pdf(origem_local)
            categoria, origem, llm = self._classificar(
                origem_local, nome, modulo, tamanho or origem_local.stat().st_size, paginas)
            nome_local = self._nome_local_livre(nome, fid, categoria, catalogo, origem_local)
            destino = catalogo.pasta / categoria / nome_local
            destino.parent.mkdir(parents=True, exist_ok=True)
            if origem_local.resolve() != destino.resolve():
                shutil.move(str(origem_local), str(destino))
            catalogo.registrar(fid, self._entrada(
                nome_canvas, nome_local, categoria, origem, atualizado_em, tamanho,
                destino, catalogo, paginas, modulo, llm, baixado_em=None,
                migrado_em=agora_iso()))
            resumo["migrados"].append(nome_canvas)
            print(f" [Canvas] PDF migrado sem baixar [{categoria} | {origem}]: {nome_local}")
            return

        # b. Novo, atualizado ou apagado do disco: baixa de novo.
        if entrada is None:
            tipo = "novos"
        elif entrada.get("updated_at") == atualizado_em:
            tipo = "recuperados"
        else:
            tipo = "atualizados"
        mantem_categoria = entrada is not None and entrada.get("nome") == nome_canvas

        parcial = catalogo.pasta / f".{fid}.part"
        self._com_retentativas(lambda: arquivo.download(str(parcial)), f"baixar {nome}")
        paginas = _contar_paginas_pdf(parcial)

        if mantem_categoria:
            categoria, origem = entrada["categoria"], entrada["origem"]
            llm = entrada.get("llm")
            nome_local = entrada["nome_local"]
        else:
            categoria, origem, llm = self._classificar(
                parcial, nome, modulo, tamanho or parcial.stat().st_size, paginas)
            nome_local = self._nome_local_livre(nome, fid, categoria, catalogo)

        destino = catalogo.pasta / categoria / nome_local
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial.replace(destino)
        if entrada and catalogo.existe_no_disco(entrada):
            antigo = catalogo.caminho_absoluto(entrada)
            if antigo.resolve() != destino.resolve():
                antigo.unlink()  # o nome mudou: remove a versão anterior

        catalogo.registrar(fid, self._entrada(
            nome_canvas, nome_local, categoria, origem, atualizado_em, tamanho,
            destino, catalogo, paginas, modulo, llm, baixado_em=agora_iso()))
        resumo[tipo].append(nome_canvas)
        resumo["baixados"].append(str(destino))
        print(f" [Canvas] PDF baixado ({tipo}) [{categoria} | {origem}]: "
              f"{categoria}/{nome_local}")

    def _classificar(self, caminho: Path, nome: str, modulo: Optional[str],
                     tamanho, paginas) -> tuple:
        """Regras do classificador.py; se indefinido, LLM; se nada, outros.

        Raises:
            LLMIndisponivel: se a LLM devolveu llm:erro_api. JSON inválido e
            confiança baixa continuam virando "outros" e são salvos.
        """
        categoria, origem = classificar(nome, modulo, None, tamanho, paginas)
        llm = None
        if categoria == "indefinido":
            r = self.classificador_llm(caminho, nome, modulo, paginas)
            if r.get("origem") == "llm:erro_api":
                raise LLMIndisponivel(r.get("justificativa") or "erro da API")
            categoria, origem = r.get("categoria"), r.get("origem", "llm")
            llm = {"confianca": r.get("confianca"), "justificativa": r.get("justificativa")}
        if categoria not in CATEGORIAS:
            categoria = "outros"
        return categoria, origem, llm

    @staticmethod
    def _nome_local_livre(nome: str, fid: str, categoria: str, catalogo: Catalogo,
                          proprio: Optional[Path] = None) -> str:
        """`nome`, ou `<base>_<file_id><ext>` se outro id já usa esse nome no curso."""
        destino = catalogo.pasta / categoria / nome
        ocupado_no_disco = destino.exists() and (
            proprio is None or destino.resolve() != Path(proprio).resolve())
        if catalogo.nome_em_uso(nome, fid) or ocupado_no_disco:
            base = Path(nome)
            return f"{base.stem}_{fid}{base.suffix}"
        return nome

    @staticmethod
    def _entrada(nome_canvas, nome_local, categoria, origem, atualizado_em, tamanho,
                 destino: Path, catalogo: Catalogo, paginas, modulo, llm,
                 baixado_em=None, migrado_em=None) -> Dict:
        entrada = {
            "nome": nome_canvas,
            "nome_local": nome_local,
            "categoria": categoria,
            "origem": origem,
            "updated_at": atualizado_em,
            "size": tamanho,
            "caminho": destino.relative_to(catalogo.pasta).as_posix(),
            "paginas": paginas,
            "modulo": modulo,
            "baixado_em": baixado_em,
        }
        if migrado_em:
            entrada["migrado_em"] = migrado_em
        if llm:
            entrada["llm"] = llm
        return entrada

    @staticmethod
    def _pdfs_soltos(pasta: Path, catalogo: Catalogo) -> Dict[str, Path]:
        """PDFs no disco que o catálogo não conhece: {nome em minúsculas: caminho}.

        Pega os soltos na raiz do curso e os das pastas antigas (conteudo/,
        listas/ da versão anterior) ou de qualquer subpasta.
        """
        registrados = catalogo.caminhos_registrados()
        soltos: Dict[str, Path] = {}
        for p in sorted(pasta.rglob("*.pdf")):
            if not p.is_file():
                continue
            if p.relative_to(pasta).as_posix().lower() in registrados:
                continue
            soltos.setdefault(p.name.lower(), p)
        return soltos

    @staticmethod
    def _remover_pastas_antigas_vazias(pasta: Path) -> None:
        """Remove pastas da organização anterior que ficaram vazias."""
        for nome in PASTAS_ANTIGAS:
            sub = pasta / nome
            if sub.is_dir() and not any(sub.iterdir()):
                sub.rmdir()

    def _salvar_assignments(self, course, pasta: Path) -> None:
        """Tarefas do curso (com description) em assignments.json, usado pelo Tutor."""
        tarefas = self._iterar_paginado(
            lambda: course.get_assignments(), f"listar as tarefas do curso {course.id}")
        dados = [
            {
                "id": a.id,
                "name": getattr(a, "name", ""),
                "description": getattr(a, "description", None),
                "due_at": getattr(a, "due_at", None),
                "submitted": getattr(a, "has_submitted_submissions", False),
            }
            for a in tarefas
        ]
        gravar_json_atomico(pasta / "assignments.json", dados)
