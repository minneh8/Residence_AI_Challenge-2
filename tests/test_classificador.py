# tests/test_classificador.py
"""Testes offline do classificador por regras.

Casos reais extraídos de data/logs/diagnostico_*.json (nome, módulo, pasta e
tamanho em bytes; páginas sempre None, pois o diagnóstico não conta páginas),
mais casos sintéticos (páginas, indefinido, camada de módulo por categoria e
palavras inteiras).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from src.agente_canvas.classificador import classificar  # noqa: E402

# (nome, modulo, pasta, tamanho, paginas, categoria_esperada)
CASES = [
    # --- 93527: Métodos de Computação Experimental e Quantitativa ---
    ("aula00.pdf", "Slides de Aula", "course files", 570814, None, "slides"),
    ("aula01.pdf", "Slides de Aula", "course files", 317731, None, "slides"),
    ("aula02.pdf", "Slides de Aula", "course files", 274095, None, "slides"),
    ("aula03.pdf", "Slides de Aula", "course files", 400330, None, "slides"),
    ("aula04.pdf", "Slides de Aula", "course files", 2796445, None, "slides"),
    ("aula05.pdf", "Slides de Aula", "course files", 502625, None, "slides"),
    ("aula06.pdf", "Slides de Aula", "course files", 2053622, None, "slides"),
    ("aula07.pdf", "Slides de Aula", "course files", 608105, None, "slides"),
    ("aula08.pdf", "Slides de Aula", "course files", 643366, None, "slides"),
    ("ex_aula03.pdf", "Atividade de Entrega", "course files", 341996, None, "listas"),
    ("ex_aula_semana6.pdf", "Atividade de Entrega", "course files", 456620, None, "listas"),
    ("lista_exercicios_01.pdf", "Atividade de Entrega", "course files", 156806, None, "listas"),
    ("PUCCampinas_MCEQ_RoteiroTrabalhoFinal.pdf", "Trabalho do Curso", "course files", 416104, None, "trabalho"),

    # --- 93511: Gerenciamento de Projetos de Eng. de Software (sem módulos) ---
    ("guia-pmbok-7-portugues.pdf", None, "course files", 73680169, None, "livros"),
    ("pmbok-6-portugues.pdf", None, "course files", 71792386, None, "livros"),
    # Sem palavra de livro, sem módulo, 9 MB (< 20 MB) e sem páginas: as regras
    # o deixam em "indefinido" (decisão de manter assim; seria tratado depois).
    ("Material de Apoio GP - ENG_SOFT.pdf", None, "course files", 9463028, None, "indefinido"),
    ("APS GESTAO DE RISCO GP.pdf", None, "course files", 5447413, None, "trabalho"),
    ("modelo Gestao de risco.pdf", None, "course files", 429623, None, "trabalho"),

    # --- 93532: Manutenção e Evolução de Software ---
    ("A1 - Apresentação Disciplina 2026-2.pdf", "Aula 03/08", "course files", 483951, None, "slides"),
    ("A2 - Evolução de Software e Leis de Lehman.pdf", "Aula 10/08", "course files", 1197857, None, "slides"),
    ("A3 - Tipos de Manutenção de Software.pdf", "Aula 17/08", "course files", 865752, None, "slides"),
    ("Engenharia_de_Software_7ed_PRESSMAN (1)_compressed.pdf", "Qualidade", "course files", 7263401, None, "livros"),

    # --- Sintéticos ---
    # Nome neutro que só vira "livros" por causa das páginas (> 100).
    ("Compilado geral de conteudo", None, None, 500000, 400, "livros"),
    # Nome neutro, sem módulo, pequeno e sem páginas -> indefinido.
    ("Arquivo avulso sem categoria", None, "course files", 120000, None, "indefinido"),

    # --- Camada de módulo por categoria ---
    ("resolucao.pdf", "Atividade de Entrega", "course files", 200000, None, "listas"),
    ("especificacao.pdf", "Trabalho do Curso", "course files", 200000, None, "trabalho"),
    # Módulo neutro não decide: cai até "indefinido".
    ("material.pdf", "Qualidade", "course files", 200000, None, "indefinido"),

    # --- Palavras inteiras: "aps" não pode casar dentro de outra palavra ---
    ("etapas do projeto.pdf", None, "course files", 200000, None, "indefinido"),
    ("mapas conceituais.pdf", None, "course files", 200000, None, "indefinido"),
]


@pytest.mark.parametrize("nome,modulo,pasta,tamanho,paginas,esperado", CASES)
def test_classificar(nome, modulo, pasta, tamanho, paginas, esperado):
    categoria, origem = classificar(nome, modulo, pasta, tamanho, paginas)
    assert categoria == esperado, (
        f"{nome}: esperado '{esperado}', obtido '{categoria}' (origem: {origem})"
    )
