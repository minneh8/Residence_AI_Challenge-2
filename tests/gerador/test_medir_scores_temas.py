"""Testes de scripts/medir_scores_temas.py, com RAG falso e sem rede."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "medir_scores_temas.py"


def carregar_script():
    """Importa o script pelo caminho (scripts/ não é um pacote Python)."""
    spec = importlib.util.spec_from_file_location("medir_scores_temas", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def buscar_com_scores(scores: dict[str, float]):
    """RAG falso: devolve um trecho com o score do tema, ou nada se o tema não estiver."""
    chamadas = []

    def buscar(pergunta, course_id, k=5):
        chamadas.append((pergunta, course_id, k))
        if pergunta not in scores:
            return []
        return [{"texto": "TEXTO DO PDF", "arquivo": "a.pdf", "pagina": 1, "pagina_fim": 1,
                 "score": scores[pergunta]}]

    buscar.chamadas = chamadas
    return buscar


def test_imprime_o_score_top1_de_cada_tema_e_nunca_o_texto(capsys):
    buscar = buscar_com_scores({"modelo OSI": 0.861, "TCP": 0.84, "fotossíntese": 0.792})
    argumentos = ["--curso", "42", "--dentro", "modelo OSI", "TCP", "--fora", "fotossíntese"]

    codigo = carregar_script().main(argumentos, buscar=buscar)

    saida = capsys.readouterr().out
    assert codigo == 0
    assert "dentro   0.861  modelo OSI" in saida
    assert "dentro   0.840  TCP" in saida
    assert "fora     0.792  fotossíntese" in saida
    assert "menor de dentro: 0.840 | maior de fora: 0.792" in saida
    assert "TEXTO DO PDF" not in saida and "a.pdf" not in saida
    assert buscar.chamadas == [
        ("modelo OSI", 42, 1), ("TCP", 42, 1), ("fotossíntese", 42, 1)
    ]


def test_curso_nao_indexado_avisa_e_sai_com_2(capsys):
    vazio = buscar_com_scores({})
    codigo = carregar_script().main(["--curso", "42", "--dentro", "x"], buscar=vazio)

    assert codigo == 2
    assert "não está indexado" in capsys.readouterr().err


def test_sem_temas_e_erro_do_argparse(capsys):
    with pytest.raises(SystemExit) as saida:
        carregar_script().main(["--curso", "42"], buscar=buscar_com_scores({}))

    assert saida.value.code == 2
    assert "pelo menos um tema" in capsys.readouterr().err
