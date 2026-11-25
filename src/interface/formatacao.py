"""Formatação de apresentação da interface do Glaux (datas e nomes em pt-BR).

Só formata para exibir: NÃO altera os dados salvos (catálogo, assignments.json,
nomes de curso) nem chama agentes. As datas do Canvas chegam em UTC (ISO 8601) e
são sempre mostradas no fuso de São Paulo (America/Sao_Paulo); o Brasil não usa
horário de verão desde 2019, então, sem o tzdata, o fuso cai para UTC-3 fixo.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo

    FUSO_SP = ZoneInfo("America/Sao_Paulo")
except Exception:  # pragma: no cover - fallback sem tzdata
    FUSO_SP = timezone(timedelta(hours=-3))

FUSO_UTC = timezone.utc

# Palavras que ficam em minúscula no meio de um nome próprio em português.
_MINUSCULAS = {"de", "da", "do", "das", "dos", "e", "em", "a", "o", "para",
               "com", "ao", "à", "na", "no", "nas", "nos", "por"}

_PARENTESES = re.compile(r"\([^)]*\)")
_COD_NUMERICO = re.compile(r"\b\d[\d-]*[a-zA-Z]?\b")
_HIFEN_ISOLADO = re.compile(r"\s+[-–]\s+")
_ESPACOS = re.compile(r"\s+")
_LETRA_NUM = re.compile(r"(?<=[A-Za-zÀ-ÿ])(?=\d)|(?<=\d)(?=[A-Za-zÀ-ÿ])")
# Numeral romano (I, II, …, VI, …, X, …): preservado em CAIXA ALTA nos títulos,
# para não virar "Vi" em "Projeto Integrador VI".
_ROMANO = re.compile(r"m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})")


# --------------------------------------------------------------------------
# Datas (sempre em America/Sao_Paulo)
# --------------------------------------------------------------------------
def _parse(valor) -> Optional[datetime]:
    """Converte ISO/datetime em datetime com fuso (UTC quando vier ingênuo)."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        dt = valor
    else:
        try:
            dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=FUSO_UTC)
    return dt


def para_sp(valor) -> Optional[datetime]:
    """datetime no fuso de São Paulo (ou None se não for uma data válida)."""
    dt = _parse(valor)
    return dt.astimezone(FUSO_SP) if dt else None


def data_curta(valor) -> str:
    """'08/12' (dia/mês no fuso de SP)."""
    dt = para_sp(valor)
    return dt.strftime("%d/%m") if dt else ""


def data_hora(valor) -> str:
    """'25/11 às 23:59' (data e hora no fuso de SP)."""
    dt = para_sp(valor)
    return f"{dt.strftime('%d/%m')} às {dt.strftime('%H:%M')}" if dt else ""


def _dias_ate(valor, agora=None) -> Optional[int]:
    """Diferença em dias de calendário (SP) entre a data e agora; None sem data."""
    dt = para_sp(valor)
    if dt is None:
        return None
    base = para_sp(agora) or datetime.now(FUSO_SP)
    return (dt.date() - base.date()).days


def data_relativa(valor, submitted: bool = False, agora=None) -> str:
    """Texto relativo da data: 'hoje às 23:59', 'amanhã às 23:59',
    'em 12 dias (08/12)', 'atrasada há 3 dias', 'encerrada em 13/10'."""
    dt = para_sp(valor)
    if dt is None:
        return "entregue" if submitted else "sem data"
    if submitted:
        return f"encerrada em {dt.strftime('%d/%m')}"
    dias = _dias_ate(valor, agora)
    hora = dt.strftime("%H:%M")
    if dias == 0:
        return f"hoje às {hora}"
    if dias == 1:
        return f"amanhã às {hora}"
    if dias > 1:
        return f"em {plural(dias, 'dia')} ({dt.strftime('%d/%m')})"
    return f"atrasada há {plural(abs(dias), 'dia')}"


def ha_quanto_tempo(valor, agora=None) -> str:
    """'há 5 min', 'há 2 horas', 'há 3 dias' desde o instante dado."""
    dt = _parse(valor)
    if dt is None:
        return "nunca"
    base = _parse(agora) or datetime.now(FUSO_UTC)
    seg = max(0, (base - dt).total_seconds())
    if seg < 60:
        return "agora mesmo"
    if seg < 3600:
        return f"há {plural(int(seg // 60), 'min', 'min')}"
    if seg < 86400:
        return f"há {plural(int(seg // 3600), 'hora')}"
    return f"há {plural(int(seg // 86400), 'dia')}"


def status_prazo(valor, submitted: bool, agora=None) -> str:
    """Status de uma tarefa: 'entregue', 'atrasada' ou 'pendente'."""
    if submitted:
        return "entregue"
    dias = _dias_ate(valor, agora)
    if dias is not None and dias < 0:
        return "atrasada"
    return "pendente"


def secao_prazo(valor, submitted: bool, agora=None) -> str:
    """Seção da tarefa: 'entregues', 'atrasadas', 'hoje', 'proximos' ou 'adiante'."""
    if submitted:
        return "entregues"
    dias = _dias_ate(valor, agora)
    if dias is None:
        return "adiante"
    if dias < 0:
        return "atrasadas"
    if dias == 0:
        return "hoje"
    if dias <= 7:
        return "proximos"
    return "adiante"


# --------------------------------------------------------------------------
# Números e plural (pt-BR)
# --------------------------------------------------------------------------
def numero_br(n) -> str:
    """Número no formato brasileiro: 1234 -> '1.234', 1234.5 -> '1.234,5'."""
    if n is None:
        return "—"
    if isinstance(n, int):
        return f"{n:,}".replace(",", ".")
    return f"{n:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def plural(n, singular: str, plural_: Optional[str] = None) -> str:
    """'1 dia', '2 dias' — número em pt-BR + palavra no singular/plural."""
    plural_ = plural_ or singular + "s"
    return f"{numero_br(n)} {singular if abs(n) == 1 else plural_}"


# --------------------------------------------------------------------------
# Nomes legíveis (sem alterar os dados salvos)
# --------------------------------------------------------------------------
def _capitalizar(palavra: str) -> str:
    return palavra[:1].upper() + palavra[1:] if palavra else palavra


def _formatar_palavra(palavra: str, primeira: bool) -> str:
    if palavra and _ROMANO.fullmatch(palavra):
        return palavra.upper()
    if not primeira and palavra in _MINUSCULAS:
        return palavra
    return _capitalizar(palavra)


def _titulo(texto: str) -> str:
    """Título em pt-BR: 1ª palavra maiúscula; 'de','e'… minúsculas; romanos em caixa."""
    palavras = texto.lower().split()
    return " ".join(_formatar_palavra(p, i == 0) for i, p in enumerate(palavras))


def nome_materia(raw: str) -> str:
    """Nome da matéria sem código de turma nem rótulos entre parênteses.

    Ex.: '218131 - MÉTODOS DE COMPUTAÇÃO EXPERIMENTAL E QUANTITATIVA (MAT)
    0101-06-26-2s' -> 'Métodos de Computação Experimental e Quantitativa'.
    """
    n = _PARENTESES.sub(" ", raw or "")
    n = _COD_NUMERICO.sub(" ", n)
    n = _HIFEN_ISOLADO.sub(" ", n)
    n = _ESPACOS.sub(" ", n).strip()
    return _titulo(n) or (raw or "").strip()


def nome_arquivo(nome: str) -> str:
    """Nome de arquivo legível: 'ex_aula_semana6.pdf' -> 'Ex Aula Semana 6'."""
    base = re.sub(r"\.pdf$", "", nome or "", flags=re.IGNORECASE)
    base = base.replace("_", " ").replace("-", " ")
    base = _LETRA_NUM.sub(" ", base)
    base = _ESPACOS.sub(" ", base).strip()
    return _titulo(base) or (nome or "")


def titulo_tarefa(raw: str) -> str:
    """Título da tarefa: mantém o texto original, só tira a caixa alta forçada.

    Quando o título vem TODO em maiúsculas, aplica capitalização normal; caso
    contrário devolve o texto como está (não inventa capitalização).
    """
    texto = (raw or "").strip()
    letras = [c for c in texto if c.isalpha()]
    if letras and all(c.isupper() for c in letras):
        return _titulo(texto.replace("_", " "))
    return texto
