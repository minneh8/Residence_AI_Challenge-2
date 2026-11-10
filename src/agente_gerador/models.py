"""Modelos de dados do gerador de questões.

Pydantic valida os dados na hora de criar o objeto: se algo não bate (campo
vazio, chave faltando, valor fora da lista), lança ValidationError dizendo o
quê. É assim que o código confere a saída do LLM sem confiar nela.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

LETRAS = ("A", "B", "C", "D")

Letra = Literal["A", "B", "C", "D"]

# Texto com pelo menos um caractere visível. Os espaços nas pontas são removidos.
TextoNaoVazio = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TrechoReferencia(BaseModel):
    """Trecho do material que sustenta a questão.

    Arquivo, página e texto vêm do RAG. O LLM só indica arquivo e página; o
    texto é copiado do trecho original pelo código.
    """

    arquivo: TextoNaoVazio
    pagina: int = Field(ge=1)
    texto: TextoNaoVazio


class QuestaoMultiplaEscolha(BaseModel):
    """Questão com 4 alternativas (A a D) e uma única correta."""

    id: TextoNaoVazio
    tipo: Literal["multipla_escolha"]
    enunciado: TextoNaoVazio
    alternativas: dict[Letra, TextoNaoVazio]
    correta: Letra
    assunto: TextoNaoVazio
    trecho_referencia: TrechoReferencia

    @field_validator("alternativas")
    @classmethod
    def _exatamente_a_ate_d(cls, alternativas: dict[str, str]) -> dict[str, str]:
        if set(alternativas) != set(LETRAS):
            raise ValueError("as alternativas devem ser exatamente A, B, C e D")
        textos = [texto.casefold() for texto in alternativas.values()]
        if len(set(textos)) != len(textos):
            raise ValueError("há alternativas com o mesmo texto")
        return {letra: alternativas[letra] for letra in LETRAS}


class QuestaoDissertativa(BaseModel):
    """Questão aberta. A rede neural avalia a resposta usando trecho_referencia."""

    id: TextoNaoVazio
    tipo: Literal["dissertativa"]
    enunciado: TextoNaoVazio
    assunto: TextoNaoVazio
    trecho_referencia: TrechoReferencia


# União discriminada: o Pydantic olha o campo "tipo" para escolher a classe.
Questao = Annotated[QuestaoMultiplaEscolha | QuestaoDissertativa, Field(discriminator="tipo")]


class ResultadoGeracao(BaseModel):
    """O que gerar_questoes devolve.

    status "ok": questoes traz as questões validadas.
    status "sem_material" ou "erro": questoes vazia e mensagem para o aluno.
    """

    status: Literal["ok", "sem_material", "erro"]
    questoes: list[Questao] = Field(default_factory=list)
    mensagem: str | None = None

    @model_validator(mode="after")
    def _status_coerente(self) -> Self:
        if self.status == "ok" and not self.questoes:
            raise ValueError('status "ok" precisa de pelo menos uma questão')
        if self.status != "ok" and self.questoes:
            raise ValueError(f'status "{self.status}" não pode trazer questões')
        if self.status != "ok" and not self.mensagem:
            raise ValueError(f'status "{self.status}" precisa de mensagem para o aluno')
        return self
