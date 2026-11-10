"""Testes dos modelos Pydantic do gerador de questões."""

import pytest
from pydantic import TypeAdapter, ValidationError
from src.agente_gerador.models import (
    Questao,
    QuestaoDissertativa,
    QuestaoMultiplaEscolha,
    ResultadoGeracao,
)

REFERENCIA = {
    "arquivo": "aula_ficticia_01.pdf",
    "pagina": 3,
    "texto": "Overfitting ocorre quando o modelo memoriza o ruído do treino.",
}

validar_questao = TypeAdapter(Questao).validate_python


def multipla(**mudancas):
    dados = {
        "id": "q1",
        "tipo": "multipla_escolha",
        "enunciado": "O que caracteriza o overfitting?",
        "alternativas": {
            "A": "Erro alto no treino e no teste",
            "B": "Erro baixo no treino e alto no teste",
            "C": "Erro igual no treino e no teste",
            "D": "Ausência de dados de teste",
        },
        "correta": "B",
        "assunto": "overfitting",
        "trecho_referencia": dict(REFERENCIA),
    }
    dados.update(mudancas)
    return dados


def dissertativa(**mudancas):
    dados = {
        "id": "q2",
        "tipo": "dissertativa",
        "enunciado": "Explique por que o overfitting prejudica a generalização.",
        "assunto": "overfitting",
        "trecho_referencia": dict(REFERENCIA),
    }
    dados.update(mudancas)
    return dados


def test_multipla_escolha_valida():
    questao = QuestaoMultiplaEscolha.model_validate(multipla())
    assert list(questao.alternativas) == ["A", "B", "C", "D"]
    assert questao.correta == "B"


def test_alternativas_saem_na_ordem_a_d():
    fora_de_ordem = {"D": "d", "B": "b", "A": "a", "C": "c"}
    questao = QuestaoMultiplaEscolha.model_validate(multipla(alternativas=fora_de_ordem))
    assert list(questao.alternativas) == ["A", "B", "C", "D"]


@pytest.mark.parametrize(
    "alternativas",
    [
        {"A": "a", "B": "b", "C": "c"},  # faltou D
        {"A": "a", "B": "b", "C": "c", "D": "d", "E": "e"},  # sobrou E
        {"A": "a", "B": "b", "C": "c", "d": "d"},  # letra minúscula
    ],
)
def test_multipla_escolha_exige_exatamente_a_ate_d(alternativas):
    with pytest.raises(ValidationError):
        QuestaoMultiplaEscolha.model_validate(multipla(alternativas=alternativas))


def test_alternativas_repetidas_sao_recusadas():
    repetidas = {"A": "Regularização", "B": "regularização ", "C": "c", "D": "d"}
    with pytest.raises(ValidationError, match="mesmo texto"):
        QuestaoMultiplaEscolha.model_validate(multipla(alternativas=repetidas))


def test_alternativa_vazia_e_recusada():
    with pytest.raises(ValidationError):
        QuestaoMultiplaEscolha.model_validate(
            multipla(alternativas={"A": "a", "B": "   ", "C": "c", "D": "d"})
        )


def test_correta_ausente_e_recusada():
    dados = multipla()
    del dados["correta"]
    with pytest.raises(ValidationError):
        QuestaoMultiplaEscolha.model_validate(dados)


@pytest.mark.parametrize("correta", ["E", "b", "", "AB"])
def test_correta_fora_de_a_d_e_recusada(correta):
    with pytest.raises(ValidationError):
        QuestaoMultiplaEscolha.model_validate(multipla(correta=correta))


@pytest.mark.parametrize("campo", ["enunciado", "assunto"])
def test_texto_vazio_e_recusado(campo):
    with pytest.raises(ValidationError):
        QuestaoMultiplaEscolha.model_validate(multipla(**{campo: "   "}))


def test_referencia_exige_pagina_positiva():
    with pytest.raises(ValidationError):
        QuestaoDissertativa.model_validate(
            dissertativa(trecho_referencia={**REFERENCIA, "pagina": 0})
        )


def test_uniao_escolhe_a_classe_pelo_tipo():
    assert isinstance(validar_questao(multipla()), QuestaoMultiplaEscolha)
    assert isinstance(validar_questao(dissertativa()), QuestaoDissertativa)


def test_tipo_desconhecido_e_recusado():
    with pytest.raises(ValidationError):
        validar_questao(dissertativa(tipo="resumo"))


def test_resultado_ok_com_questoes():
    resultado = ResultadoGeracao(status="ok", questoes=[multipla(), dissertativa()])
    assert [type(q) for q in resultado.questoes] == [QuestaoMultiplaEscolha, QuestaoDissertativa]
    assert resultado.mensagem is None


@pytest.mark.parametrize(
    "dados",
    [
        {"status": "ok"},  # ok sem questões
        {"status": "erro", "mensagem": "falhou", "questoes": [dissertativa()]},  # erro com questões
        {"status": "sem_material"},  # sem mensagem para o aluno
    ],
)
def test_resultado_incoerente_e_recusado(dados):
    with pytest.raises(ValidationError):
        ResultadoGeracao.model_validate(dados)
