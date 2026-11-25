"""Testes do serviço do gerador: gerar_questoes, validar_saida e chamar_groq.

O RAG e o LLM são falsos (dubles_gerador.py): nada usa rede nem .env.
"""

import json
import logging
from types import SimpleNamespace

import groq
import httpx
import pytest
from dubles_gerador import (
    TRECHO_FRACO,
    TRECHOS,
    BuscarFalso,
    LLMFalso,
    questao_dissertativa,
    questao_multipla,
    referencia,
    resposta,
)
from prompts.agente_gerador_prompts import (
    EXEMPLO_SAIDA,
    EXEMPLO_TIPOS,
    EXEMPLO_TRECHOS,
    PROMPT_SISTEMA_GERADOR,
)
from src.agente_gerador import service
from src.agente_gerador.models import QuestaoDissertativa, QuestaoMultiplaEscolha
from src.agente_gerador.service import (
    SCORE_MINIMO,
    RespostaLLM,
    SaidaInvalida,
    gerar_questoes,
    selecionar_trechos,
    validar_saida,
)

AMBOS = ("multipla_escolha", "dissertativa")
TRECHOS_BONS = [t for t in TRECHOS if t is not TRECHO_FRACO]


def gerar(buscar, llm, quantidade=2, tipos=AMBOS, tema="overfitting"):
    return gerar_questoes(tema, 42, quantidade, tipos, buscar=buscar, chamar_llm=llm)


def sem_chave(questao: dict, chave: str) -> dict:
    copia = dict(questao)
    del copia[chave]
    return copia


def erro_de_conexao() -> groq.APIConnectionError:
    pedido = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return groq.APIConnectionError(request=pedido)


# --- Caminho feliz -----------------------------------------------------------


def test_gera_a_quantidade_pedida(buscar):
    llm = LLMFalso(
        resposta(questao_multipla(1), questao_dissertativa(2), questao_multipla(3, TRECHOS[2]))
    )
    resultado = gerar(buscar, llm, quantidade=3)
    assert resultado.status == "ok"
    assert len(resultado.questoes) == 3
    assert resultado.mensagem is None
    assert len(llm.chamadas) == 1


def test_multipla_escolha_sai_com_4_alternativas(buscar):
    llm = LLMFalso(resposta(questao_multipla(1), questao_multipla(2, TRECHOS[1])))
    resultado = gerar(buscar, llm, tipos=("multipla_escolha",))
    for questao in resultado.questoes:
        assert isinstance(questao, QuestaoMultiplaEscolha)
        assert list(questao.alternativas) == ["A", "B", "C", "D"]
        assert questao.correta in ("A", "B", "C", "D")


def test_texto_da_referencia_e_o_original_do_rag(buscar):
    com_texto = {**referencia(TRECHOS[1]), "texto": "texto inventado pelo LLM"}
    llm = LLMFalso(resposta(questao_dissertativa(1, trecho_referencia=com_texto)))
    resultado = gerar(buscar, llm, quantidade=1, tipos=("dissertativa",))
    ref = resultado.questoes[0].trecho_referencia
    assert ref.texto == TRECHOS[1]["texto"]
    assert (ref.arquivo, ref.pagina) == (TRECHOS[1]["arquivo"], TRECHOS[1]["pagina"])
    assert ref.pagina_fim == TRECHOS[1]["pagina_fim"] == 6  # copiado do RAG, não do LLM


def test_pagina_fim_mandada_pelo_llm_e_ignorada(buscar):
    inventada = {**referencia(TRECHOS[0]), "pagina_fim": 99}
    llm = LLMFalso(resposta(questao_dissertativa(1, TRECHOS[0], trecho_referencia=inventada)))
    resultado = gerar(buscar, llm, quantidade=1, tipos=("dissertativa",))
    assert resultado.questoes[0].trecho_referencia.pagina_fim == TRECHOS[0]["pagina_fim"]


def test_ids_sao_renumerados(buscar):
    llm = LLMFalso(resposta(questao_multipla(1, id="x"), questao_dissertativa(2, id="x")))
    resultado = gerar(buscar, llm)
    assert [q.id for q in resultado.questoes] == ["q1", "q2"]


def test_tipos_pedidos_sao_respeitados(buscar):
    llm = LLMFalso(resposta(questao_dissertativa(1), questao_dissertativa(2, TRECHOS[2])))
    resultado = gerar(buscar, llm, tipos=("dissertativa",))
    assert resultado.status == "ok"
    assert all(isinstance(q, QuestaoDissertativa) for q in resultado.questoes)
    assert '<tipos>["dissertativa"]</tipos>' in llm.chamadas[0][1]["content"]


def test_mensagens_tem_regras_no_system_e_dados_no_user(buscar):
    llm = LLMFalso(resposta(questao_multipla(1), questao_dissertativa(2)))
    gerar(buscar, llm)
    sistema, usuario = llm.chamadas[0]
    assert sistema == {"role": "system", "content": PROMPT_SISTEMA_GERADOR}
    assert usuario["role"] == "user"
    assert "<tema>overfitting</tema>" in usuario["content"]
    assert "<quantidade>2</quantidade>" in usuario["content"]


# --- Saídas inválidas: nunca viram questão ------------------------------------


def test_correta_ausente_gera_erro(buscar):
    invalida = resposta(questao_multipla(1), sem_chave(questao_multipla(2, TRECHOS[1]), "correta"))
    llm = LLMFalso(invalida, invalida)
    resultado = gerar(buscar, llm, tipos=("multipla_escolha",))
    assert resultado.status == "erro"
    assert resultado.questoes == []  # nem a questão boa é devolvida
    assert len(llm.chamadas) == 2


@pytest.mark.parametrize(
    "ref",
    [
        {"arquivo": "aula_que_nao_existe.pdf", "pagina": 3},
        {"arquivo": "aula_ficticia_01.pdf", "pagina": 99},
        {"arquivo": "aula_ficticia_01.pdf", "pagina": "3"},  # página como texto
        {"arquivo": "aula_ficticia_01.pdf", "pagina": True},
        referencia(TRECHO_FRACO),  # existe no RAG, mas foi descartado pelo score
        None,
    ],
)
def test_referencia_inventada_gera_erro(buscar, ref):
    invalida = resposta(questao_multipla(1), questao_dissertativa(2, trecho_referencia=ref))
    llm = LLMFalso(invalida, invalida)
    resultado = gerar(buscar, llm)
    assert resultado.status == "erro"
    assert len(llm.chamadas) == 2


def test_json_truncado_gera_erro(buscar):
    cortado_no_meio = '{"questoes": [{"id": "q1", "tipo": "multi'
    truncada = RespostaLLM(conteudo=cortado_no_meio, finish_reason="length")
    llm = LLMFalso(truncada, truncada)
    resultado = gerar(buscar, llm)
    assert resultado.status == "erro"
    assert len(llm.chamadas) == 2


def test_length_e_erro_mesmo_com_json_completo():
    completa = resposta(questao_multipla(1), questao_dissertativa(2), finish_reason="length")
    with pytest.raises(SaidaInvalida, match="truncada"):
        validar_saida(completa, 2, AMBOS, TRECHOS_BONS)


def test_tipo_nao_pedido_gera_erro(buscar):
    fora_do_pedido = resposta(questao_multipla(1), questao_dissertativa(2))
    llm = LLMFalso(fora_do_pedido, fora_do_pedido)
    resultado = gerar(buscar, llm, tipos=("multipla_escolha",))
    assert resultado.status == "erro"


@pytest.mark.parametrize(
    "saida",
    [
        RespostaLLM(conteudo="isto não é JSON", finish_reason="stop"),
        RespostaLLM(conteudo=None, finish_reason="stop"),
        RespostaLLM(conteudo="[]", finish_reason="stop"),
        RespostaLLM(conteudo='{"perguntas": []}', finish_reason="stop"),
        RespostaLLM(conteudo='{"questoes": ["q1", "q2"]}', finish_reason="stop"),
        resposta(questao_multipla(1)),  # 1 questão, pedido de 2
        resposta(questao_multipla(1), questao_dissertativa(2), questao_multipla(3)),  # 3
        resposta(questao_multipla(1), questao_dissertativa(2), finish_reason="content_filter"),
        resposta(questao_multipla(1), questao_dissertativa(2), finish_reason=None),
        resposta(
            questao_multipla(1, alternativas={"A": "a", "B": "b", "C": "c"}),
            questao_dissertativa(2),
        ),
        resposta(
            questao_multipla(1, alternativas={"A": "igual", "B": "Igual", "C": "c", "D": "d"}),
            questao_dissertativa(2),
        ),
        resposta(questao_multipla(1, correta="E"), questao_dissertativa(2)),
        resposta(questao_multipla(1), questao_dissertativa(2, enunciado="   ")),
        resposta(questao_multipla(1), questao_dissertativa(2, tipo="resumo")),
    ],
    ids=[
        "texto-solto",
        "conteudo-vazio",
        "lista-no-lugar-de-objeto",
        "chave-errada",
        "itens-que-nao-sao-objetos",
        "faltou-questao",
        "sobrou-questao",
        "content-filter",
        "sem-finish-reason",
        "3-alternativas",
        "alternativa-repetida",
        "correta-fora-de-a-d",
        "enunciado-vazio",
        "tipo-desconhecido",
    ],
)
def test_saidas_invalidas_sao_recusadas(saida):
    with pytest.raises(SaidaInvalida):
        validar_saida(saida, 2, AMBOS, TRECHOS_BONS)


# --- Nova tentativa ------------------------------------------------------------


def test_invalida_na_primeira_e_valida_na_segunda(buscar):
    faltou_uma = resposta(questao_multipla(1))
    llm = LLMFalso(faltou_uma, resposta(questao_multipla(1), questao_dissertativa(2)))
    resultado = gerar(buscar, llm)
    assert resultado.status == "ok"
    assert len(llm.chamadas) == 2
    assert llm.chamadas[0] == llm.chamadas[1]  # o mesmo pedido nas duas tentativas


def test_duas_falhas_viram_erro_com_mensagem(buscar):
    lixo = RespostaLLM(conteudo="lixo", finish_reason="stop")
    llm = LLMFalso(lixo, lixo)
    resultado = gerar(buscar, llm)
    assert resultado.status == "erro"
    assert resultado.mensagem == service.MENSAGEM_ERRO
    assert resultado.questoes == []
    assert len(llm.chamadas) == service.TENTATIVAS == 2


def test_falha_da_api_conta_como_tentativa(buscar):
    llm = LLMFalso(erro_de_conexao(), resposta(questao_multipla(1), questao_dissertativa(2)))
    resultado = gerar(buscar, llm)
    assert resultado.status == "ok"
    assert len(llm.chamadas) == 2


def test_duas_falhas_da_api_viram_erro(buscar):
    llm = LLMFalso(erro_de_conexao(), erro_de_conexao())
    assert gerar(buscar, llm).status == "erro"


def test_erro_de_programacao_nao_e_engolido(buscar):
    llm = LLMFalso(RuntimeError("bug no código"))
    with pytest.raises(RuntimeError, match="bug no código"):
        gerar(buscar, llm)


def test_motivo_da_falha_vai_para_o_log(buscar, caplog):
    truncada = RespostaLLM(conteudo='{"questoes": [', finish_reason="length")
    llm = LLMFalso(truncada, truncada)
    with caplog.at_level(logging.WARNING, logger="src.agente_gerador.service"):
        gerar(buscar, llm)
    assert caplog.text.count("truncada") == 2


# --- Sem material ------------------------------------------------------------------


def test_sem_material_nao_chama_o_llm():
    buscar = BuscarFalso([TRECHO_FRACO])
    llm = LLMFalso()  # fila vazia: se for chamado, o teste falha
    resultado = gerar(buscar, llm, tema="  redes neurais  ")
    assert resultado.status == "sem_material"
    assert resultado.questoes == []
    assert resultado.mensagem == (
        'Não encontrei material sobre "redes neurais" nesta disciplina. '
        "Confira se o tema está escrito como nas aulas."
    )
    assert llm.chamadas == []
    assert buscar.chamadas[0]["pergunta"] == "redes neurais"


def test_rag_sem_resultado_e_curso_nao_indexado():
    llm = LLMFalso()
    resultado = gerar(BuscarFalso([]), llm)
    assert resultado.status == "sem_material"
    assert resultado.mensagem == service.MENSAGEM_CURSO_NAO_INDEXADO
    assert llm.chamadas == []


def sem_material_do_llm() -> RespostaLLM:
    return RespostaLLM(conteudo='{"sem_material": true, "questoes": []}', finish_reason="stop")


def test_llm_recusa_e_vira_sem_material_sem_nova_tentativa(buscar):
    llm = LLMFalso(sem_material_do_llm())  # só uma resposta na fila: uma segunda chamada falharia
    resultado = gerar(buscar, llm, quantidade=3, tema="  redes neurais  ")
    assert resultado.status == "sem_material"
    assert resultado.questoes == []
    assert resultado.mensagem == (
        'O material encontrado sobre "redes neurais" não é suficiente para 3 questões. '
        "Tente um tema mais específico ou peça menos questões."
    )
    assert len(llm.chamadas) == 1


def test_validar_saida_devolve_none_quando_o_llm_recusa():
    assert validar_saida(sem_material_do_llm(), 2, AMBOS, TRECHOS_BONS) is None


def test_sem_material_false_explicito_vale_como_resposta_normal():
    dados = json.loads(resposta(questao_multipla(1), questao_dissertativa(2)).conteudo)
    saida = RespostaLLM(conteudo=json.dumps({"sem_material": False, **dados}), finish_reason="stop")
    assert len(validar_saida(saida, 2, AMBOS, TRECHOS_BONS)) == 2


@pytest.mark.parametrize(
    "conteudo",
    [
        {"sem_material": True, "questoes": ["q1"]},  # tudo ou nada
        {"sem_material": "true", "questoes": []},  # texto no lugar de booleano
        {"sem_material": True},  # falta a lista "questoes"
    ],
    ids=["recusa-com-questoes", "sem-material-texto", "recusa-sem-lista"],
)
def test_sem_material_mal_formado_e_saida_invalida(conteudo):
    saida = RespostaLLM(conteudo=json.dumps(conteudo), finish_reason="stop")
    with pytest.raises(SaidaInvalida):
        validar_saida(saida, 2, AMBOS, TRECHOS_BONS)


def test_recusa_com_questoes_usa_a_nova_tentativa(buscar):
    mal_formada = RespostaLLM(
        conteudo=json.dumps({"sem_material": True, "questoes": [questao_multipla(1)]}),
        finish_reason="stop",
    )
    llm = LLMFalso(mal_formada, resposta(questao_multipla(1), questao_dissertativa(2)))
    resultado = gerar(buscar, llm)
    assert resultado.status == "ok"
    assert len(llm.chamadas) == 2


# --- Trechos e busca -----------------------------------------------------------------


def test_trechos_abaixo_do_limiar_nao_vao_para_o_llm(buscar):
    llm = LLMFalso(resposta(questao_multipla(1), questao_dissertativa(2)))
    gerar(buscar, llm)
    usuario = llm.chamadas[0][1]["content"]
    assert TRECHO_FRACO["arquivo"] not in usuario
    for trecho in TRECHOS_BONS:
        assert trecho["texto"] in usuario


def test_selecionar_trechos_filtra_desduplica_e_ordena():
    trechos = [
        {"texto": "a", "arquivo": "x.pdf", "pagina": 1, "score": 0.85},
        {"texto": "b", "arquivo": "x.pdf", "pagina": 1, "score": 0.9},  # mesma página, maior score
        {"texto": "c", "arquivo": "y.pdf", "pagina": 2, "score": SCORE_MINIMO},  # no limiar: fica
        {"texto": "   ", "arquivo": "z.pdf", "pagina": 3, "score": 0.95},  # texto vazio
        {"texto": "d", "arquivo": "w.pdf", "pagina": 4, "score": SCORE_MINIMO - 0.01},  # abaixo
    ]
    selecionados = selecionar_trechos(trechos)
    assert [(t["arquivo"], t["texto"]) for t in selecionados] == [("x.pdf", "b"), ("y.pdf", "c")]


def test_selecionar_trechos_tira_o_mesmo_texto_vindo_de_outro_arquivo():
    trechos = [
        {"texto": "Camadas do modelo", "arquivo": "copia.pdf", "pagina": 2, "score": 0.87},
        {"texto": "camadas  do\nmodelo", "arquivo": "original.pdf", "pagina": 2, "score": 0.88},
        {"texto": "Outro conteúdo", "arquivo": "copia.pdf", "pagina": 3, "score": 0.80},
    ]
    selecionados = selecionar_trechos(trechos)
    assert [(t["arquivo"], t["pagina"]) for t in selecionados] == [
        ("original.pdf", 2),  # o repetido de maior score fica
        ("copia.pdf", 3),
    ]


@pytest.mark.parametrize(("quantidade", "k"), [(1, 10), (5, 10), (10, 10)])
def test_k_do_rag_acompanha_a_quantidade(quantidade, k):
    buscar = BuscarFalso([])  # sem material: aqui só interessa a chamada ao RAG
    gerar(buscar, LLMFalso(), quantidade=quantidade)
    assert buscar.chamadas == [{"pergunta": "overfitting", "course_id": 42, "k": k}]


# --- Entradas inválidas ---------------------------------------------------------------


@pytest.mark.parametrize(
    "mudanca",
    [
        {"tema": ""},
        {"tema": "   "},
        {"quantidade": 0},
        {"quantidade": 11},
        {"quantidade": 2.5},
        {"quantidade": True},
        {"tipos": ()},
        {"tipos": ("resumo",)},
        {"tipos": "dissertativa"},
        {"course_id": "42"},
    ],
)
def test_entrada_invalida_levanta_value_error(mudanca):
    buscar, llm = BuscarFalso(TRECHOS), LLMFalso()
    argumentos = {"tema": "overfitting", "course_id": 42, "quantidade": 2, "tipos": AMBOS}
    with pytest.raises(ValueError):
        gerar_questoes(**(argumentos | mudanca), buscar=buscar, chamar_llm=llm)
    assert buscar.chamadas == []
    assert llm.chamadas == []


def test_tipos_repetidos_viram_um_so(buscar):
    llm = LLMFalso(resposta(questao_dissertativa(1)))
    gerar(buscar, llm, quantidade=1, tipos=("dissertativa", "dissertativa"))
    assert '<tipos>["dissertativa"]</tipos>' in llm.chamadas[0][1]["content"]


# --- Exemplo do prompt -----------------------------------------------------------------


def test_exemplo_do_prompt_passa_na_validacao_do_codigo():
    saida = RespostaLLM(conteudo=json.dumps(EXEMPLO_SAIDA), finish_reason="stop")
    questoes = validar_saida(saida, len(EXEMPLO_SAIDA["questoes"]), EXEMPLO_TIPOS, EXEMPLO_TRECHOS)
    assert len(questoes) == 2


def test_copiar_o_exemplo_do_prompt_gera_erro(buscar):
    copia = RespostaLLM(conteudo=json.dumps(EXEMPLO_SAIDA), finish_reason="stop")
    llm = LLMFalso(copia, copia)
    assert gerar(buscar, llm).status == "erro"  # exemplo_ficticio.pdf nunca está nos trechos


# --- chamar_groq, sem rede ---------------------------------------------------------------


def test_chamar_groq_usa_os_parametros_combinados(monkeypatch):
    capturado = {}

    class ChatGroqFalso:
        def __init__(self, **opcoes):
            capturado["opcoes"] = opcoes

        def invoke(self, mensagens):
            capturado["mensagens"] = mensagens
            return SimpleNamespace(
                content='{"questoes": []}', response_metadata={"finish_reason": "stop"}
            )

    monkeypatch.setattr(service, "load_dotenv", lambda caminho: False)  # não lê o .env real
    monkeypatch.setenv("GROQ_API_KEY", "chave-falsa-de-teste")
    monkeypatch.setattr(service, "ChatGroq", ChatGroqFalso)

    mensagens = [{"role": "user", "content": "oi"}]
    assert service.chamar_groq(mensagens) == RespostaLLM('{"questoes": []}', "stop")
    assert capturado["mensagens"] == mensagens
    assert capturado["opcoes"] == {
        "model": "openai/gpt-oss-20b",
        "api_key": "chave-falsa-de-teste",
        "temperature": 0.6,
        "reasoning_effort": "low",
        "timeout": 60,
        "max_retries": 0,
        "model_kwargs": {
            "top_p": 0.95,
            "max_completion_tokens": 8000,
            "response_format": {"type": "json_object"},
            "include_reasoning": False,
        },
    }


def test_chamar_groq_chega_ao_sdk_groq_com_o_pedido_combinado(monkeypatch):
    """Usa o ChatGroq de verdade e troca só o cliente do SDK groq, para ver o pedido final."""
    capturado = {}

    class CompletionsFalso:
        def create(self, **pedido):
            capturado["pedido"] = pedido
            mensagem = {"role": "assistant", "content": '{"questoes": []}'}
            return {"choices": [{"message": mensagem, "finish_reason": "stop"}], "usage": {}}

    class ChatGroqComClienteFalso(service.ChatGroq):
        def __init__(self, **opcoes):
            super().__init__(**opcoes)
            capturado["sdk"] = (self.client._client.timeout, self.client._client.max_retries)
            self.client = CompletionsFalso()

    monkeypatch.setattr(service, "load_dotenv", lambda caminho: False)  # não lê o .env real
    monkeypatch.setenv("GROQ_API_KEY", "chave-falsa-de-teste")
    monkeypatch.setattr(service, "ChatGroq", ChatGroqComClienteFalso)

    mensagens = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert service.chamar_groq(mensagens) == RespostaLLM('{"questoes": []}', "stop")
    assert capturado["sdk"] == (60, 0)
    pedido = capturado["pedido"]
    assert pedido["messages"] == mensagens
    assert {chave: pedido[chave] for chave in (
        "model", "temperature", "top_p", "max_completion_tokens",
        "reasoning_effort", "response_format", "include_reasoning",
    )} == {
        "model": "openai/gpt-oss-20b",
        "temperature": 0.6,
        "top_p": 0.95,
        "max_completion_tokens": 8000,
        "reasoning_effort": "low",
        "response_format": {"type": "json_object"},
        "include_reasoning": False,
    }
    assert "max_tokens" not in pedido  # o limite vai só como max_completion_tokens


def test_chamar_groq_sem_chave_avisa_onde_preencher(monkeypatch):
    caminhos = []
    monkeypatch.setattr(service, "load_dotenv", caminhos.append)  # registra, não lê
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        service.chamar_groq([])
    assert caminhos == [service.CAMINHO_ENV]
    assert service.CAMINHO_ENV.name == ".env"
    raiz = service.CAMINHO_ENV.parent  # a raiz do projeto: a pasta que tem src/ e prompts/
    assert (raiz / "src" / "agente_gerador").is_dir()
    assert (raiz / "prompts").is_dir()
