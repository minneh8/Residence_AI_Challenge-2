"""Fixtures do gerador de questões. Nada aqui usa rede, .env ou data/raw."""

import pytest
from dubles_gerador import TRECHOS, BuscarFalso


@pytest.fixture
def buscar():
    """RAG falso com os trechos fictícios (um deles abaixo do limiar de score)."""
    return BuscarFalso(TRECHOS)
