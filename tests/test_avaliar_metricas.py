# tests/test_avaliar_metricas.py
"""Testes das métricas do scripts/avaliar.py (HitRate, Recall, Precision, MRR)."""

import importlib.util
from pathlib import Path

import pytest

_CAMINHO = Path(__file__).resolve().parents[1] / "scripts" / "avaliar.py"
_spec = importlib.util.spec_from_file_location("avaliar", _CAMINHO)
avaliar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(avaliar)

# Gabarito: aula01 p.17 e p.18, aula02 p.5 -> 3 páginas relevantes.
RESPOSTAS = [{"arquivo": "aula01.pdf", "paginas": [17, 18]},
             {"arquivo": "aula02.pdf", "paginas": [5]}]


def t(arquivo, pagina, pagina_fim=None):
    return {"arquivo": arquivo, "pagina": pagina, "pagina_fim": pagina_fim or pagina, "score": 0.8}


def test_recall_conta_paginas_relevantes_recuperadas():
    trechos = [t("aula01.pdf", 17), t("aula03.pdf", 17), t("aula02.pdf", 4)]
    assert avaliar.recall_paginas(trechos, RESPOSTAS) == pytest.approx(1 / 3)


def test_recall_trecho_de_varias_paginas_cobre_intervalo():
    trechos = [t("aula01.pdf", 16, 18), t("aula02.pdf", 5)]
    assert avaliar.recall_paginas(trechos, RESPOSTAS) == 1.0


def test_precision_divide_por_k():
    trechos = [t("aula01.pdf", 17), t("aula01.pdf", 18), t("aula09.pdf", 1)]
    assert avaliar.precisao(trechos, RESPOSTAS, k=5) == pytest.approx(2 / 5)
    assert avaliar.precisao(trechos, RESPOSTAS, k=3) == pytest.approx(2 / 3)


def test_mesmo_numero_de_pagina_em_outro_arquivo_nao_conta():
    trechos = [t("aula02.pdf", 17)]
    assert avaliar.recall_paginas(trechos, RESPOSTAS) == 0.0
    assert avaliar.precisao(trechos, RESPOSTAS, k=1) == 0.0
    assert avaliar.posicao_acerto(trechos, RESPOSTAS) is None


def test_resumir_media_por_pergunta():
    linhas = [
        {"pos": 1, "recall": 1.0, "precision": 0.4, "trechos": [t("a.pdf", 1)]},
        {"pos": 2, "recall": 0.5, "precision": 0.2, "trechos": [t("a.pdf", 1, 3)]},
        {"pos": None, "recall": 0.0, "precision": 0.0, "trechos": []},
    ]
    r = avaliar.resumir(linhas)
    assert r["hitrate"] == pytest.approx(2 / 3)
    assert r["recall"] == pytest.approx(0.5)
    assert r["precision"] == pytest.approx(0.2)
    assert r["mrr"] == pytest.approx((1 + 0.5) / 3)
    assert r["paginas"] == pytest.approx(2.0)
