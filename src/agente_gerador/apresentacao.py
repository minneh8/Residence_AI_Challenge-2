"""Texto das questões para mostrar ao aluno no terminal.

Usado por scripts/testar_gerador.py e pela esteira (src/graph.py). formatar()
devolve o texto em vez de imprimir, para ser testável sem capturar a saída.
"""

from collections.abc import Mapping
from typing import Any

from .models import QuestaoMultiplaEscolha, ResultadoGeracao

TAMANHO_FONTE = 160  # caracteres do trecho mostrados em cada questão


def formatar(resultado: ResultadoGeracao) -> str:
    """Monta o texto do resultado: status, mensagem e cada questão com a fonte."""
    linhas = [f"status: {resultado.status}"]
    if resultado.mensagem:
        linhas.append(f"mensagem para o aluno: {resultado.mensagem}")
    for questao in resultado.questoes:
        linhas.append("")
        linhas.append(f"[{questao.id}] {questao.tipo} | assunto: {questao.assunto}")
        linhas.append(f"  {questao.enunciado}")
        if isinstance(questao, QuestaoMultiplaEscolha):
            for letra, texto in questao.alternativas.items():
                marca = "*" if letra == questao.correta else " "
                linhas.append(f"   {marca} {letra}) {texto}")
        ref = questao.trecho_referencia
        resumo = ref.texto if len(ref.texto) <= TAMANHO_FONTE else ref.texto[:TAMANHO_FONTE] + "..."
        linhas.append(f"  fonte: {ref.arquivo}, {paginas(ref.pagina, ref.pagina_fim)}: {resumo}")
    return "\n".join(linhas)


def paginas(inicio: int, fim: int) -> str:
    """ "p. 3" para uma página só e "p. 3–5" (com meia-risca) para várias."""
    return f"p. {inicio}" if inicio == fim else f"p. {inicio}–{fim}"


def resultado_do_estado(estado: Mapping[str, Any]) -> ResultadoGeracao | None:
    """Remonta o ResultadoGeracao a partir do estado final do grafo.

    Devolve None quando o gerador não rodou (sem --questoes, generation_status
    fica None). O Pydantic revalida as questões, que no estado são dicts.
    """
    status = estado.get("generation_status")
    if status is None:
        return None
    return ResultadoGeracao(
        status=status,
        mensagem=estado.get("generation_message"),
        questoes=estado.get("generated_questions") or [],
    )
