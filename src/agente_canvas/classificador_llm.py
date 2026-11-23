# src/agente_canvas/classificador_llm.py
"""Fallback de LLM do classificador de materiais.

Só é chamado quando as regras do classificador.py devolvem "indefinido". Envia
à Groq (mesmo cliente e modelo do Tutor, temperatura 0) apenas material público
do curso: o texto das 3 primeiras páginas (até ~4000 caracteres), o nome do
arquivo, o módulo e o número de páginas. Nenhum dado do aluno é enviado.

A resposta precisa ser um JSON validado por pydantic (RespostaLLM). JSON
inválido, erro da API ou confiança abaixo de CONFIANCA_MINIMA viram "outros".

O service.py salva no catálogo o resultado aceito ("llm") e os casos
llm:json_invalido e llm:confianca_baixa (como "outros"), que não são
recalculados enquanto o updated_at do arquivo no Canvas não mudar. Já
llm:erro_api NÃO é salvo: o arquivo é tentado de novo na próxima sincronização.
"""

import json
import logging
import re
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from prompts.agente_canvas_prompts import CLASSIFICADOR_SYSTEM_PROMPT
from src.rag.extracao import extrair_pdf

logger = logging.getLogger(__name__)

CATEGORIAS = ("slides", "listas", "trabalho", "livros", "outros")
CONFIANCA_MINIMA = 0.6
PAGINAS_LIDAS = 3
MAX_CARACTERES_TEXTO = 4000
MODELO_PADRAO = "openai/gpt-oss-20b"  # o mesmo do TutorService

_OBJETO_JSON = re.compile(r"\{.*\}", re.DOTALL)


class RespostaLLM(BaseModel):
    categoria: Literal["slides", "listas", "trabalho", "livros", "outros"]
    confianca: float = Field(ge=0.0, le=1.0)
    justificativa: str = Field(max_length=300)


def texto_inicial(caminho: Path) -> str:
    """Texto das primeiras páginas do PDF, limitado a MAX_CARACTERES_TEXTO."""
    try:
        paginas = extrair_pdf(Path(caminho), course_id=0, max_paginas=PAGINAS_LIDAS)
    except Exception as e:
        logger.warning("Não foi possível extrair texto de %s: %s", caminho, e)
        return ""
    texto = "\n\n".join(p["texto"] for p in paginas if p["texto"])
    return texto[:MAX_CARACTERES_TEXTO]


def _criar_llm():
    """Cliente da Groq igual ao do Tutor (langchain_groq.ChatGroq)."""
    import os

    from langchain_groq import ChatGroq

    return ChatGroq(
        model_name=MODELO_PADRAO,
        temperature=0,
        groq_api_key=os.getenv("GROQ_API_KEY"),
    )


def _mensagens(nome: str, modulo: Optional[str], paginas: Optional[int], texto: str):
    from langchain_core.messages import HumanMessage, SystemMessage

    return [
        SystemMessage(content=CLASSIFICADOR_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Nome do arquivo: {nome}\n"
            f"Módulo: {modulo or '(sem módulo)'}\n"
            f"Páginas: {paginas if paginas is not None else 'desconhecido'}\n\n"
            f"Texto das primeiras páginas:\n{texto or '(sem texto extraível)'}"
        )),
    ]


def _resultado(categoria: str, origem: str, confianca: float, justificativa: str) -> dict:
    return {
        "categoria": categoria,
        "origem": origem,
        "confianca": confianca,
        "justificativa": justificativa,
    }


def interpretar_resposta(conteudo: str) -> dict:
    """Valida a resposta da LLM e aplica o limiar de confiança.

    Returns:
        {"categoria", "origem", "confianca", "justificativa"}. "origem" é
        "llm" quando a categoria foi aceita e "llm:<motivo>" quando caiu em
        "outros" (json_invalido, confianca_baixa).
    """
    achado = _OBJETO_JSON.search(conteudo or "")
    try:
        if not achado:
            raise ValueError("resposta sem objeto JSON")
        resposta = RespostaLLM.model_validate(json.loads(achado.group(0)))
    except (ValueError, ValidationError) as e:
        logger.warning("Resposta inválida da LLM (%s): %r", e, (conteudo or "")[:200])
        return _resultado("outros", "llm:json_invalido", 0.0, "resposta da LLM fora do formato")

    if resposta.confianca < CONFIANCA_MINIMA:
        return _resultado(
            "outros", "llm:confianca_baixa", resposta.confianca,
            f"LLM sugeriu '{resposta.categoria}' com confiança baixa: {resposta.justificativa}",
        )
    return _resultado(resposta.categoria, "llm", resposta.confianca, resposta.justificativa)


def classificar_llm(caminho: Path, nome: str, modulo: Optional[str] = None,
                    paginas: Optional[int] = None, llm=None) -> dict:
    """Classifica um PDF indefinido pela LLM. Nunca levanta exceção.

    Args:
        caminho: PDF já baixado (lido só nas primeiras páginas).
        nome, modulo, paginas: metadados do arquivo.
        llm: objeto com .invoke(mensagens) -> resposta com .content. Se None,
            cria o cliente da Groq. Os testes passam um cliente simulado.
    """
    texto = texto_inicial(caminho)
    try:
        cliente = llm if llm is not None else _criar_llm()
        resposta = cliente.invoke(_mensagens(nome, modulo, paginas, texto))
        conteudo = getattr(resposta, "content", resposta)
    except Exception as e:
        logger.warning("Erro ao chamar a LLM para classificar %s: %s", nome, e)
        return _resultado("outros", "llm:erro_api", 0.0, f"erro na chamada da LLM: {type(e).__name__}")
    return interpretar_resposta(str(conteudo or ""))
