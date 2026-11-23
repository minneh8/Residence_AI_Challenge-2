# src/agente_canvas/catalogo.py
"""Catálogo de arquivos por curso e estado de sincronização por aluno.

Catálogo do curso: data/raw/<course_id>/_arquivos.json, chaveado pelo id do
arquivo no Canvas (string). Cada entrada:

    nome        nome do arquivo no Canvas (display_name)
    nome_local  nome do arquivo no disco (pode ter o sufixo _<file_id>)
    categoria   slides | listas | trabalho | livros | outros
    origem      regra que decidiu (ex.: "modulo:aula", "nome:lista", "llm")
    updated_at  updated_at do Canvas na última vez em que o arquivo foi tratado
    size        tamanho em bytes informado pelo Canvas
    caminho     caminho relativo à pasta do curso (ex.: "slides/aula03.pdf")
    paginas     número de páginas (None se não deu para contar)
    modulo      nome do módulo no Canvas (None se o arquivo não está em módulo)
    baixado_em  quando o arquivo foi baixado (None se veio de migração)
    migrado_em  quando um PDF já existente foi registrado sem baixar (opcional)
    llm         {"confianca", "justificativa"} quando a categoria veio da LLM

O catálogo é compartilhado entre alunos: se outro aluno já baixou o arquivo
com o mesmo updated_at, basta registrá-lo.

Estado do aluno: data/canvas_state/<user_id>.json, com o id real do Canvas.
Por curso: ultimo_updated_at, ultimo_file_id e sincronizado_em. Só é gravado
no fim de uma sincronização do curso sem falhas.

Toda gravação é atômica: escreve em <arquivo>.tmp e depois renomeia.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

NOME_CATALOGO = "_arquivos.json"


def agora_iso() -> str:
    """Data e hora atual em UTC, no formato do Canvas (ex.: 2026-11-23T14:05:00Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def para_datetime(valor) -> Optional[datetime]:
    """Converte o updated_at do Canvas (ISO 8601, com "Z") em datetime com fuso."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))


def gravar_json_atomico(caminho: Path, dados) -> None:
    """Grava `dados` em JSON escrevendo num .tmp e renomeando por cima."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(caminho.name + ".tmp")
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    temporario.replace(caminho)


def ler_json(caminho: Path, padrao):
    """Lê um JSON; devolve `padrao` se o arquivo não existir ou estiver corrompido."""
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


class Catalogo:
    """Catálogo de um curso (data/raw/<course_id>/_arquivos.json)."""

    def __init__(self, pasta_curso: Path):
        self.pasta = Path(pasta_curso)
        self.caminho = self.pasta / NOME_CATALOGO
        self.entradas: dict[str, dict] = ler_json(self.caminho, {})

    def get(self, file_id) -> Optional[dict]:
        return self.entradas.get(str(file_id))

    def registrar(self, file_id, entrada: dict) -> None:
        """Grava a entrada e salva o catálogo na hora (sobrevive a interrupções)."""
        self.entradas[str(file_id)] = entrada
        self.salvar()

    def salvar(self) -> None:
        gravar_json_atomico(self.caminho, self.entradas)

    def caminho_absoluto(self, entrada: dict) -> Path:
        return self.pasta / entrada["caminho"]

    def existe_no_disco(self, entrada: Optional[dict]) -> bool:
        return bool(entrada) and self.caminho_absoluto(entrada).is_file()

    def caminhos_registrados(self) -> set[str]:
        """Caminhos relativos (minúsculos) de todos os arquivos do catálogo."""
        return {e["caminho"].lower() for e in self.entradas.values() if e.get("caminho")}

    def ids_ausentes_no_disco(self) -> set[str]:
        """Ids do catálogo cujo arquivo sumiu do disco."""
        return {fid for fid, e in self.entradas.items() if not self.existe_no_disco(e)}

    def nome_em_uso(self, nome_local: str, exceto_id) -> bool:
        """True se outro id do catálogo já usa esse nome no disco (em qualquer pasta)."""
        alvo = nome_local.lower()
        return any(
            fid != str(exceto_id) and (e.get("nome_local") or "").lower() == alvo
            for fid, e in self.entradas.items()
        )


class EstadoAluno:
    """Estado de sincronização de um aluno (data/canvas_state/<user_id>.json)."""

    def __init__(self, pasta_estado: Path, user_id):
        self.caminho = Path(pasta_estado) / f"{user_id}.json"
        self.dados: dict = ler_json(self.caminho, {})

    def do_curso(self, course_id) -> Optional[dict]:
        return self.dados.get(str(course_id))

    def gravar_curso(self, course_id, ultimo_updated_at, ultimo_file_id) -> None:
        """Registra o fim de uma sincronização bem-sucedida do curso."""
        self.dados[str(course_id)] = {
            "ultimo_updated_at": ultimo_updated_at,
            "ultimo_file_id": ultimo_file_id,
            "sincronizado_em": agora_iso(),
        }
        gravar_json_atomico(self.caminho, self.dados)
