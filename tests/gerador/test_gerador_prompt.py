"""Testes do prompt do gerador de questões."""

import json

from prompts.agente_gerador_prompts import (
    EXEMPLO_SAIDA,
    EXEMPLO_TRECHOS,
    PROMPT_SISTEMA_GERADOR,
    montar_prompt_usuario,
)
from pydantic import TypeAdapter
from src.agente_gerador.models import Questao

TRECHOS = [
    {
        "texto": "Regularização L2 penaliza pesos grandes para reduzir a variância.",
        "arquivo": "aula_ficticia_02.pdf",
        "pagina": 2,
        "score": 0.77,
    }
]


def _bloco(prompt: str, tag: str) -> str:
    return prompt.split(f"<{tag}>", 1)[1].split(f"</{tag}>", 1)[0]


def test_prompt_do_usuario_tem_as_tags_em_ordem():
    prompt = montar_prompt_usuario("regularização", 3, ("dissertativa",), TRECHOS)
    tags = ["<tema>", "<quantidade>", "<tipos>", "<trechos>", "</trechos>"]
    posicoes = [prompt.index(tag) for tag in tags]
    assert posicoes == sorted(posicoes)
    assert "<tema>regularização</tema>" in prompt
    assert "<quantidade>3</quantidade>" in prompt
    assert json.loads(_bloco(prompt, "tipos")) == ["dissertativa"]


def test_trechos_vao_como_json_sem_score():
    prompt = montar_prompt_usuario("regularização", 1, ("dissertativa",), TRECHOS)
    assert json.loads(_bloco(prompt, "trechos")) == [
        {
            "arquivo": "aula_ficticia_02.pdf",
            "pagina": 2,
            "texto": "Regularização L2 penaliza pesos grandes para reduzir a variância.",
        }
    ]
    assert "score" not in prompt


def test_acentos_ficam_legiveis_para_o_modelo():
    prompt = montar_prompt_usuario("regularização", 1, ("dissertativa",), TRECHOS)
    assert "\\u" not in prompt


def test_prompt_de_sistema_traz_as_regras():
    for regra in (
        "<trechos> e </trechos>",
        '"A", "B", "C" e "D"',
        "todas as anteriores",
        "não copie o texto do trecho",
        "português do Brasil",
        "somente com o JSON",
    ):
        assert regra in PROMPT_SISTEMA_GERADOR


def test_exemplo_aparece_inteiro_no_prompt():
    assert json.dumps(EXEMPLO_SAIDA, ensure_ascii=False, indent=2) in PROMPT_SISTEMA_GERADOR


def test_exemplo_do_prompt_passa_nos_modelos():
    validar = TypeAdapter(Questao).validate_python
    textos = {(t["arquivo"], t["pagina"]): t["texto"] for t in EXEMPLO_TRECHOS}
    for item in EXEMPLO_SAIDA["questoes"]:
        ref = item["trecho_referencia"]
        texto = textos[(ref["arquivo"], ref["pagina"])]
        validar({**item, "trecho_referencia": {**ref, "texto": texto}})
