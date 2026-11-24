"""Testes de scripts/avaliar_gerador.py, com RAG e LLM falsos e sem rede."""

import importlib.util
import logging
from pathlib import Path

import groq
import httpx
import pytest
from dubles_gerador import (
    TRECHOS,
    BuscarFalso,
    LLMFalso,
    questao_dissertativa,
    questao_multipla,
    resposta,
)
from src.agente_gerador.service import RespostaLLM

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "avaliar_gerador.py"
SEM_MATERIAL = RespostaLLM(conteudo='{"sem_material": true, "questoes": []}', finish_reason="stop")


def carregar_script():
    """Importa o script pelo caminho (scripts/ não é um pacote Python)."""
    spec = importlib.util.spec_from_file_location("avaliar_gerador", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def duas_questoes():
    return resposta(
        questao_multipla(1, TRECHOS[0], correta="B"), questao_dissertativa(2, TRECHOS[1])
    )


def relogio_falso():
    """Relógio que anda 2 s a cada leitura: cada geração leva 2 s."""
    tempo = [0.0]

    def ler():
        tempo[0] += 2.0
        return tempo[0]

    return ler


def rodar(argumentos, llm):
    pausas = []
    modulo = carregar_script()
    codigo = modulo.main(
        argumentos, buscar=BuscarFalso(TRECHOS), chamar_llm=llm,
        dormir=pausas.append, relogio=relogio_falso(),
    )
    return codigo, pausas


def test_mede_status_chamadas_falhas_e_letras(capsys, caplog, tmp_path):
    # Como no uso real: o logging da raiz em ERROR não pode esconder os avisos das falhas.
    caplog.set_level(logging.ERROR)
    so_uma = resposta(questao_multipla(1, TRECHOS[0], correta="B"))  # pedido era 2
    llm = LLMFalso(duas_questoes(), so_uma, duas_questoes(), SEM_MATERIAL)
    saida = tmp_path / "avaliacao" / "resultado.md"
    argumentos = [
        "--curso", "42", "--quantidade", "2", "--pausa", "5",
        "--dentro", "overfitting", "regularização", "--fora", "fotossíntese",
        "--saida", str(saida),
    ]

    codigo, pausas = rodar(argumentos, llm)

    texto = saida.read_text(encoding="utf-8")
    assert codigo == 0
    assert texto == capsys.readouterr().out
    assert pausas == [5.0, 5.0]  # entre os temas, não antes do primeiro
    assert "| dentro | overfitting | ok | 1 | — | 2.0 | B → " in texto
    assert "| dentro | regularização | ok | 2 | quantidade errada | 2.0 | B → " in texto
    assert "| fora | fotossíntese | sem_material | 1 | — | 2.0 | — |" in texto
    assert "- Temas de dentro (2): ok 2 · sem_material 0 · erro 0" in texto
    assert "- Temas de fora (1): ok 0 · sem_material 1 · erro 0" in texto
    assert "- ok na 1ª tentativa: 1 de 2" in texto
    assert "- Retentativas: 1 (motivos: quantidade errada 1)" in texto
    assert "- Letra correta antes de embaralhar: A 0 · B 2 · C 0 · D 0" in texto


def test_nada_do_conteudo_vai_para_o_relatorio(capsys):
    argumentos = ["--curso", "42", "--quantidade", "2", "--dentro", "overfitting"]
    rodar(argumentos, LLMFalso(duas_questoes()))

    texto = capsys.readouterr().out
    for trecho in TRECHOS:
        assert trecho["texto"] not in texto
    assert "Pergunta de múltipla escolha" not in texto
    assert "Opção" not in texto


def test_falha_da_api_conta_chamada_e_motivo(capsys):
    pedido = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    limite = groq.RateLimitError(
        "Error code: 429 - limite", response=httpx.Response(429, request=pedido), body=None
    )
    llm = LLMFalso(limite, limite)

    rodar(["--curso", "42", "--quantidade", "2", "--dentro", "overfitting"], llm)

    texto = capsys.readouterr().out
    falhas = "limite do Groq (429), limite do Groq (429)"
    assert f"| dentro | overfitting | erro | 2 | {falhas} |" in texto


@pytest.mark.parametrize(
    ("mensagem", "motivo"),
    [
        ("tentativa 1 de 2 falhou: Error code: 429 - {...}", "limite do Groq (429)"),
        ("tentativa 1 de 2 falhou: Error code: 400 - {...}", "JSON recusado pelo Groq (400)"),
        ("tentativa 1 de 2 falhou: vieram 5 questões, mas o pedido era 3", "quantidade errada"),
        ("a questão 1 cita um trecho que não foi recuperado: {...}", "referência inventada"),
        ("JSON inválido: Expecting value", "outra"),
    ],
)
def test_motivo_da_falha(mensagem, motivo):
    assert carregar_script().motivo_da_falha(mensagem) == motivo


def test_letras_do_llm_le_so_as_multiplas():
    conteudo = resposta(
        questao_multipla(1, correta="C"), questao_dissertativa(2), questao_multipla(3, correta="A")
    ).conteudo
    assert carregar_script().letras_do_llm(conteudo) == ["C", "A"]
    assert carregar_script().letras_do_llm("não é JSON") == []


def test_sem_temas_e_erro_do_argparse(capsys):
    with pytest.raises(SystemExit) as saida:
        rodar(["--curso", "42"], LLMFalso())
    assert saida.value.code == 2
    assert "pelo menos um tema" in capsys.readouterr().err
