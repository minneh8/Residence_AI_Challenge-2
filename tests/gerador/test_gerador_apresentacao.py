"""Testes de src/agente_gerador/apresentacao.py: o texto das questões e a volta do estado."""

from dubles_gerador import TRECHOS, questao_dissertativa, questao_multipla
from src.agente_gerador.apresentacao import TAMANHO_FONTE, formatar, resultado_do_estado
from src.agente_gerador.models import ResultadoGeracao


def com_texto(questao: dict, trecho: dict) -> dict:
    """Questão como sai do gerador: o código copia o texto do trecho para a referência."""
    questao["trecho_referencia"]["texto"] = trecho["texto"]
    return questao


def resultado_ok() -> ResultadoGeracao:
    return ResultadoGeracao(
        status="ok",
        questoes=[
            com_texto(questao_multipla(1, TRECHOS[0]), TRECHOS[0]),
            com_texto(questao_dissertativa(2, TRECHOS[1]), TRECHOS[1]),
        ],
    )


def test_formatar_mostra_status_questoes_e_fonte():
    texto = formatar(resultado_ok())
    linhas = texto.splitlines()

    assert linhas[0] == "status: ok"
    assert "[q1] multipla_escolha | assunto:" in texto
    assert "[q2] dissertativa | assunto:" in texto
    assert sum(linha.startswith("   * ") for linha in linhas) == 1  # só a correta marcada
    assert f"fonte: {TRECHOS[0]['arquivo']}, p. {TRECHOS[0]['pagina']}:" in texto


def test_formatar_corta_trecho_longo():
    longo = dict(TRECHOS[0], texto="x" * (TAMANHO_FONTE + 50))
    resultado = ResultadoGeracao(
        status="ok", questoes=[com_texto(questao_dissertativa(1, longo), longo)]
    )

    linha_fonte = formatar(resultado).splitlines()[-1]

    assert linha_fonte.endswith("x" * TAMANHO_FONTE + "...")


def test_formatar_sem_questoes_mostra_a_mensagem():
    resultado = ResultadoGeracao(status="sem_material", mensagem="Procure o professor.")

    assert formatar(resultado).splitlines() == [
        "status: sem_material",
        "mensagem para o aluno: Procure o professor.",
    ]


def test_resultado_do_estado_sem_gerador_devolve_none():
    assert resultado_do_estado({"tema": "overfitting"}) is None
    assert resultado_do_estado({"generation_status": None}) is None


def test_resultado_do_estado_remonta_as_questoes_dos_dicts():
    original = resultado_ok()
    estado = {
        "generation_status": "ok",
        "generation_message": None,
        "generated_questions": [q.model_dump() for q in original.questoes],
    }

    assert resultado_do_estado(estado) == original
