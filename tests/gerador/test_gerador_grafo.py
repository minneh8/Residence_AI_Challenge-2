"""O gerador dentro da esteira (src/graph.py): o grafo e a opção --questoes.

Só compila o grafo e lê as opções; nada chama Canvas, RAG ou LLM.
"""

import pytest
from src import graph
from src.agente_gerador.service import TETO_QUESTOES


def test_grafo_compila_com_o_gerador_depois_do_tutor():
    desenho = graph.build_glaux_graph().get_graph()
    arestas = {(aresta.source, aresta.target) for aresta in desenho.edges}

    assert "gerador_questoes" in desenho.nodes
    assert ("tutor_agent", "gerador_questoes") in arestas
    assert ("gerador_questoes", "__end__") in arestas
    assert ("tutor_agent", "__end__") not in arestas


@pytest.mark.parametrize(
    ("argumentos", "erro"),
    [
        (["--questoes", "3"], "--questoes exige --tema e --curso"),
        (["--questoes", "3", "--tema", "overfitting"], "--questoes exige --tema e --curso"),
        (["--questoes", "3", "--curso", "42"], "--questoes exige --tema e --curso"),
        (["--questoes", "0", "--tema", "overfitting", "--curso", "42"], f"de 1 a {TETO_QUESTOES}"),
        (
            ["--questoes", str(TETO_QUESTOES + 1), "--tema", "overfitting", "--curso", "42"],
            f"de 1 a {TETO_QUESTOES}",
        ),
    ],
)
def test_opcao_questoes_invalida_para_antes_da_esteira(monkeypatch, capsys, argumentos, erro):
    def nao_deve_rodar():
        raise AssertionError("a esteira não deveria rodar")

    monkeypatch.setattr(graph, "build_glaux_graph", nao_deve_rodar)
    monkeypatch.setattr("sys.argv", ["graph.py", *argumentos])

    with pytest.raises(SystemExit) as saida:
        graph.main()

    assert saida.value.code == 2  # código do argparse para opção inválida
    assert erro in capsys.readouterr().err
