"""Testes do embaralhamento das alternativas (embaralhar_alternativas e depende_da_ordem).

Todo sorteio usa random.Random com semente fixa: a mesma semente dá sempre a mesma
ordem, então os testes não dependem da sorte.
"""

import random
from collections import Counter

import pytest
from dubles_gerador import LLMFalso, questao_dissertativa, questao_multipla, resposta
from src.agente_gerador.models import QuestaoDissertativa, QuestaoMultiplaEscolha
from src.agente_gerador.service import (
    depende_da_ordem,
    embaralhar_alternativas,
    gerar_questoes,
)

TEXTO = {"arquivo": "aula_ficticia_01.pdf", "pagina": 3, "texto": "Texto do trecho."}


def multipla(**mudancas) -> QuestaoMultiplaEscolha:
    dados = questao_multipla(1, **mudancas)
    dados["trecho_referencia"] = TEXTO
    return QuestaoMultiplaEscolha(**dados)


def dissertativa() -> QuestaoDissertativa:
    dados = questao_dissertativa(2)
    dados["trecho_referencia"] = TEXTO
    return QuestaoDissertativa(**dados)


def test_semente_fixa_da_a_ordem_esperada_e_remapeia_a_correta():
    # random.Random(42) embaralha ["A", "B", "C", "D"] para ["C", "B", "D", "A"]:
    # a nova A recebe a antiga C, a nova B a antiga B, a nova C a antiga D e a nova D a antiga A.
    original = multipla(correta="A")

    [embaralhada] = embaralhar_alternativas([original], random.Random(42))

    assert embaralhada.alternativas == {
        "A": original.alternativas["C"],
        "B": original.alternativas["B"],
        "C": original.alternativas["D"],
        "D": original.alternativas["A"],
    }
    assert embaralhada.correta == "D"


@pytest.mark.parametrize("semente", range(20))
def test_texto_da_correta_e_o_conjunto_de_alternativas_nao_mudam(semente):
    original = multipla(correta="C")

    [embaralhada] = embaralhar_alternativas([original], random.Random(semente))

    assert embaralhada.alternativas[embaralhada.correta] == original.alternativas["C"]
    assert sorted(embaralhada.alternativas.values()) == sorted(original.alternativas.values())
    assert list(embaralhada.alternativas) == ["A", "B", "C", "D"]
    assert embaralhada.enunciado == original.enunciado
    assert embaralhada.trecho_referencia == original.trecho_referencia


def test_mesma_semente_da_o_mesmo_resultado():
    questoes = [multipla(), multipla(correta="D")]

    primeira = embaralhar_alternativas(questoes, random.Random(7))
    segunda = embaralhar_alternativas(questoes, random.Random(7))

    assert primeira == segunda


def test_a_correta_se_espalha_pelas_quatro_letras():
    # O LLM pôs todas na B; depois do sorteio, cada letra deve aparecer perto de 1/4 das vezes.
    questoes = [multipla(correta="B") for _ in range(400)]

    letras = Counter(q.correta for q in embaralhar_alternativas(questoes, random.Random(0)))

    assert set(letras) == {"A", "B", "C", "D"}
    assert all(70 <= quantas <= 130 for quantas in letras.values())  # 100 esperadas por letra


def test_dissertativa_fica_como_veio():
    original = dissertativa()

    assert embaralhar_alternativas([original], random.Random(0)) == [original]


@pytest.mark.parametrize(
    "alternativas",
    [
        {"A": "Só L1", "B": "Só L2", "C": "Todas as anteriores", "D": "Outra"},
        {"A": "Só L1", "B": "Só L2", "C": "Outra", "D": "Nenhuma das ANTERIORES"},
        {"A": "Só L1", "B": "Só L2", "C": "Alternativa A e B", "D": "Outra"},
        {"A": "Só L1", "B": "As alternativas A e C", "C": "Outra", "D": "Mais uma"},
    ],
    ids=["todas-as-anteriores", "nenhuma-das-anteriores", "alternativa-A", "alternativas-A-e-C"],
)
def test_questao_que_depende_da_ordem_fica_na_ordem_original(alternativas):
    original = multipla(alternativas=alternativas, correta="C")

    assert depende_da_ordem(original)
    assert embaralhar_alternativas([original], random.Random(42)) == [original]


def test_alternativa_no_enunciado_tambem_conta():
    original = multipla(enunciado="Por que a alternativa B está errada?")

    assert depende_da_ordem(original)


def test_letra_minuscula_depois_de_alternativa_nao_conta():
    # "a alternativa a ser escolhida": o "a" é artigo, não a letra A.
    original = multipla(enunciado="Qual é a alternativa a ser escolhida pelo analista?")

    assert not depende_da_ordem(original)


def test_so_as_questoes_que_dependem_da_ordem_ficam_paradas():
    presa = multipla(alternativas={"A": "a", "B": "b", "C": "c", "D": "Todas as anteriores"})
    livre = multipla(correta="A")

    resultado = embaralhar_alternativas([presa, livre], random.Random(42))

    assert resultado[0] == presa
    assert resultado[1].correta == "D"  # mesma ordem do primeiro teste: semente 42


def test_gerar_questoes_embaralha_com_o_rng_passado(buscar):
    llm = LLMFalso(resposta(questao_multipla(1, correta="A"), questao_dissertativa(2)))

    resultado = gerar_questoes(
        "overfitting", 42, 2, buscar=buscar, chamar_llm=llm, rng=random.Random(42)
    )

    multipla_gerada, dissertativa_gerada = resultado.questoes
    assert multipla_gerada.correta == "D"
    assert multipla_gerada.alternativas["D"] == "Opção A da questão 1"
    assert dissertativa_gerada.tipo == "dissertativa"
