"""Geração de questões a partir do material da disciplina.

Fluxo de gerar_questoes():

    buscar trechos no RAG -> descartar os fracos (score < SCORE_MINIMO)
    -> nenhum trecho: "sem_material", sem chamar o LLM
    -> chamar o LLM -> validar a saída no código -> "ok"
    -> saída inválida ou falha da API: uma nova tentativa; duas falhas: "erro"

As funções são puras e testáveis sem LangGraph e sem rede: o RAG e o LLM entram
como parâmetros (buscar e chamar_llm). Só chamar_groq() fala com a internet.
"""

import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import openai
from dotenv import load_dotenv
from prompts.agente_gerador_prompts import PROMPT_SISTEMA_GERADOR, montar_prompt_usuario
from pydantic import TypeAdapter, ValidationError

from src.rag import buscar as buscar_no_rag

from .models import Questao, ResultadoGeracao

logger = logging.getLogger(__name__)

TETO_QUESTOES = 10
# Provisório. O RAG usa similaridade de cosseno do modelo E5, que costuma ficar
# entre 0.7 e 1.0 mesmo para texto sem relação com o tema: com 0.5, o status
# "sem_material" quase nunca acontece. Calibrar com a dupla do RAG usando
# avaliacao/perguntas.json.
SCORE_MINIMO = 0.5
K_MINIMO = 5  # trechos pedidos ao RAG: max(K_MINIMO, quantidade)
TIPOS_VALIDOS = ("multipla_escolha", "dissertativa")
TENTATIVAS = 2  # a primeira chamada e uma nova tentativa

MODELO = "openai/gpt-oss-20b"
TEMPERATURA = 0.6
TOP_P = 0.95
LIMITE_TOKENS = 8000
ESFORCO_RACIOCINIO = "low"
TEMPO_LIMITE_S = 60
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
CAMINHO_ENV = Path(__file__).resolve().parents[2] / ".env"  # .env na raiz do projeto

MENSAGEM_SEM_MATERIAL = (
    'Não encontrei material sobre "{tema}" nesta disciplina. Procure o professor.'
)
MENSAGEM_ERRO = "Não consegui gerar as questões agora. Tente de novo em alguns minutos."

_validar_questao = TypeAdapter(Questao).validate_python


@dataclass(frozen=True)
class RespostaLLM:
    """O que interessa da resposta do LLM: o texto e o motivo de ter parado."""

    conteudo: str | None
    finish_reason: str | None


ChamarLLM = Callable[[list[dict]], RespostaLLM]
Buscar = Callable[..., list[dict]]


class SaidaInvalida(Exception):
    """A saída do LLM não passou na validação. A mensagem diz o motivo."""


def selecionar_trechos(trechos: Sequence[dict], limiar: float = SCORE_MINIMO) -> list[dict]:
    """Escolhe os trechos que servem de material para as questões.

    Descarta os de score abaixo do limiar e os de texto vazio. Se dois trechos
    tiverem o mesmo (arquivo, pagina), fica o de maior score. A ordem final é
    por score decrescente.
    """
    melhores: dict[tuple[str, int], dict] = {}
    for trecho in trechos:
        if trecho["score"] < limiar or not str(trecho["texto"]).strip():
            continue
        chave = (trecho["arquivo"], trecho["pagina"])
        if chave not in melhores or trecho["score"] > melhores[chave]["score"]:
            melhores[chave] = trecho
    return sorted(melhores.values(), key=lambda t: t["score"], reverse=True)


def montar_mensagens(
    tema: str, quantidade: int, tipos: Sequence[str], trechos: Sequence[dict]
) -> list[dict]:
    """Mensagens para o LLM: regras no system, dados do pedido no user."""
    return [
        {"role": "system", "content": PROMPT_SISTEMA_GERADOR},
        {"role": "user", "content": montar_prompt_usuario(tema, quantidade, tipos, trechos)},
    ]


def validar_saida(
    resposta: RespostaLLM, quantidade: int, tipos: Sequence[str], trechos: Sequence[dict]
) -> list[Questao]:
    """Confere a resposta do LLM e devolve as questões prontas.

    Lança SaidaInvalida na primeira regra que falhar. O texto de cada
    trecho_referencia é sempre o original do RAG, e os ids viram q1, q2, ...
    """
    if resposta.finish_reason == "length":
        raise SaidaInvalida("resposta truncada: acabou o limite de tokens (finish_reason=length)")
    if resposta.finish_reason != "stop":
        raise SaidaInvalida(f"o modelo parou por {resposta.finish_reason!r}, e não por 'stop'")

    try:
        dados = json.loads(resposta.conteudo or "")
    except json.JSONDecodeError as erro:
        raise SaidaInvalida(f"JSON inválido: {erro}") from erro
    if not isinstance(dados, dict) or not isinstance(dados.get("questoes"), list):
        raise SaidaInvalida('o JSON deve ser um objeto com a lista "questoes"')
    itens = dados["questoes"]
    if len(itens) != quantidade:
        raise SaidaInvalida(f"vieram {len(itens)} questões, mas o pedido era {quantidade}")

    originais = {(t["arquivo"], t["pagina"]): t for t in trechos}
    questoes = []
    for numero, item in enumerate(itens, start=1):
        if not isinstance(item, dict):
            raise SaidaInvalida(f"a questão {numero} não é um objeto JSON")
        if item.get("tipo") not in tipos:
            raise SaidaInvalida(
                f"a questão {numero} é do tipo {item.get('tipo')!r}, fora dos pedidos {list(tipos)}"
            )
        original = _trecho_citado(item.get("trecho_referencia"), originais)
        if original is None:
            raise SaidaInvalida(
                f"a questão {numero} cita um trecho que não foi recuperado: "
                f"{item.get('trecho_referencia')!r}"
            )
        completa = {
            **item,
            "id": f"q{numero}",
            "trecho_referencia": {
                "arquivo": original["arquivo"],
                "pagina": original["pagina"],
                "texto": original["texto"],
            },
        }
        try:
            questoes.append(_validar_questao(completa))
        except ValidationError as erro:
            raise SaidaInvalida(f"a questão {numero} é inválida: {_resumo(erro)}") from erro
    return questoes


def chamar_groq(mensagens: list[dict]) -> RespostaLLM:
    """Chama o modelo no Groq pelo cliente openai (a API do Groq é compatível).

    A chave vem de GROQ_API_KEY, lida do .env na raiz do projeto. O cliente não repete
    chamadas sozinho (max_retries=0): a nova tentativa é decidida em
    gerar_questoes, para serem no máximo TENTATIVAS chamadas por pedido.
    """
    load_dotenv(CAMINHO_ENV)
    chave = os.getenv("GROQ_API_KEY", "")
    if not chave:
        raise RuntimeError(
            "GROQ_API_KEY não encontrada. Crie o arquivo .env na raiz do projeto "
            "(a pasta que tem src/ e prompts/) com a linha GROQ_API_KEY=<sua chave>."
        )
    cliente = openai.OpenAI(
        base_url=GROQ_BASE_URL, api_key=chave, timeout=TEMPO_LIMITE_S, max_retries=0
    )
    resposta = cliente.chat.completions.create(
        model=MODELO,
        messages=mensagens,
        temperature=TEMPERATURA,
        top_p=TOP_P,
        max_completion_tokens=LIMITE_TOKENS,
        reasoning_effort=ESFORCO_RACIOCINIO,
        response_format={"type": "json_object"},
        # O cliente openai não conhece include_reasoning; vai direto no corpo do pedido.
        extra_body={"include_reasoning": False},
    )
    escolha = resposta.choices[0]
    return RespostaLLM(conteudo=escolha.message.content, finish_reason=escolha.finish_reason)


def gerar_questoes(
    tema: str,
    course_id: int,
    quantidade: int = 5,
    tipos: Sequence[str] = TIPOS_VALIDOS,
    *,
    buscar: Buscar = buscar_no_rag,
    chamar_llm: ChamarLLM = chamar_groq,
) -> ResultadoGeracao:
    """Gera questões sobre o tema a partir do material da disciplina.

    Args:
        tema: assunto das questões (vem do Planejador).
        course_id: id da disciplina no Canvas.
        quantidade: total de questões, de 1 a TETO_QUESTOES.
        tipos: tipos permitidos, "multipla_escolha" e/ou "dissertativa".
        buscar: busca do RAG; os testes passam uma falsa.
        chamar_llm: chamada ao LLM; os testes passam uma falsa.

    Returns:
        ResultadoGeracao com status "ok", "sem_material" ou "erro".

    Raises:
        ValueError: entrada inválida (tema vazio, quantidade fora de 1 a
            TETO_QUESTOES, tipo desconhecido). É erro de quem chama.
    """
    tipos = _validar_entrada(tema, course_id, quantidade, tipos)
    tema = tema.strip()

    trechos = selecionar_trechos(buscar(tema, course_id, k=max(K_MINIMO, quantidade)))
    if not trechos:
        return ResultadoGeracao(
            status="sem_material", mensagem=MENSAGEM_SEM_MATERIAL.format(tema=tema)
        )

    mensagens = montar_mensagens(tema, quantidade, tipos, trechos)
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            questoes = validar_saida(chamar_llm(mensagens), quantidade, tipos, trechos)
        except (SaidaInvalida, openai.OpenAIError) as erro:
            logger.warning(
                "Gerador de questões: tentativa %d de %d falhou: %s", tentativa, TENTATIVAS, erro
            )
            continue
        return ResultadoGeracao(status="ok", questoes=questoes)
    return ResultadoGeracao(status="erro", mensagem=MENSAGEM_ERRO)


def _validar_entrada(
    tema: str, course_id: int, quantidade: int, tipos: Sequence[str]
) -> tuple[str, ...]:
    """Confere os parâmetros de gerar_questoes e devolve os tipos sem repetição."""
    if not isinstance(tema, str) or not tema.strip():
        raise ValueError("O tema não pode ser vazio.")
    if isinstance(course_id, bool) or not isinstance(course_id, int):
        raise ValueError("course_id deve ser um número inteiro.")
    if isinstance(quantidade, bool) or not isinstance(quantidade, int):
        raise ValueError("quantidade deve ser um número inteiro.")
    if not 1 <= quantidade <= TETO_QUESTOES:
        raise ValueError(f"quantidade deve estar entre 1 e {TETO_QUESTOES}.")
    if isinstance(tipos, str):
        raise ValueError('tipos deve ser uma lista ou tupla, por exemplo ("dissertativa",).')
    tipos = tuple(dict.fromkeys(tipos))  # tira repetidos e mantém a ordem
    if not tipos:
        raise ValueError("Peça pelo menos um tipo de questão.")
    desconhecidos = [t for t in tipos if t not in TIPOS_VALIDOS]
    if desconhecidos:
        raise ValueError(f"Tipos desconhecidos: {desconhecidos}. Use {list(TIPOS_VALIDOS)}.")
    return tipos


def _trecho_citado(referencia: object, originais: dict[tuple[str, int], dict]) -> dict | None:
    """Acha o trecho original citado por (arquivo, pagina), ou devolve None."""
    if not isinstance(referencia, dict):
        return None
    arquivo, pagina = referencia.get("arquivo"), referencia.get("pagina")
    if not isinstance(arquivo, str) or isinstance(pagina, bool) or not isinstance(pagina, int):
        return None
    return originais.get((arquivo, pagina))


def _resumo(erro: ValidationError) -> str:
    """Resume os erros do Pydantic numa linha: campo e motivo."""
    return "; ".join(
        f"{'.'.join(str(parte) for parte in e['loc'])}: {e['msg']}" for e in erro.errors()
    )
