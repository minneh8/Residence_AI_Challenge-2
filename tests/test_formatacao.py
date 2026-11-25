"""Testes da formatação de apresentação (src/interface/formatacao.py).

Tudo offline e determinístico: as datas "agora" são fixas nos testes.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.interface import formatacao as fmt

# "Agora" fixo para os textos relativos: 25/11/2026 10:00 em SP (13:00 UTC).
AGORA = datetime(2026, 11, 25, 13, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Fuso: UTC -> America/Sao_Paulo
# --------------------------------------------------------------------------
def test_converte_utc_para_sao_paulo():
    # 2026-11-26T02:59:59Z = 25/11 às 23:59 em SP (UTC-3).
    assert fmt.data_hora("2026-11-26T02:59:59Z") == "25/11 às 23:59"
    assert fmt.data_curta("2026-11-26T02:59:59Z") == "25/11"


def test_data_invalida_ou_vazia_vira_string_vazia():
    assert fmt.data_hora(None) == ""
    assert fmt.data_curta("não é data") == ""
    assert fmt.para_sp(None) is None


# --------------------------------------------------------------------------
# Texto relativo
# --------------------------------------------------------------------------
def test_relativa_hoje_e_amanha():
    # 25/11 23:59 em SP = 26/11 02:59Z.
    assert fmt.data_relativa("2026-11-26T02:59:59Z", agora=AGORA) == "hoje às 23:59"
    # 26/11 23:59 em SP = 27/11 02:59Z.
    assert fmt.data_relativa("2026-11-27T02:59:59Z", agora=AGORA) == "amanhã às 23:59"


def test_relativa_futuro_com_data():
    # 07/12 09:00 em SP, 12 dias de calendário após 25/11.
    assert fmt.data_relativa("2026-12-07T12:00:00Z", agora=AGORA) == "em 12 dias (07/12)"


def test_relativa_atrasada():
    assert fmt.data_relativa("2026-11-22T12:00:00Z", agora=AGORA) == "atrasada há 3 dias"
    assert fmt.data_relativa("2026-11-24T12:00:00Z", agora=AGORA) == "atrasada há 1 dia"


def test_relativa_entregue_fica_encerrada():
    assert fmt.data_relativa("2026-10-13T12:00:00Z", submitted=True,
                             agora=AGORA) == "encerrada em 13/10"
    assert fmt.data_relativa(None, submitted=True) == "entregue"
    assert fmt.data_relativa(None, submitted=False) == "sem data"


# --------------------------------------------------------------------------
# Status e seções de prazo
# --------------------------------------------------------------------------
def test_status_prazo():
    assert fmt.status_prazo("2026-11-22T12:00:00Z", False, AGORA) == "atrasada"
    assert fmt.status_prazo("2026-12-10T12:00:00Z", False, AGORA) == "pendente"
    assert fmt.status_prazo("2026-11-22T12:00:00Z", True, AGORA) == "entregue"


def test_secao_prazo():
    assert fmt.secao_prazo("2026-11-22T12:00:00Z", False, AGORA) == "atrasadas"
    assert fmt.secao_prazo("2026-11-26T02:59:59Z", False, AGORA) == "hoje"
    assert fmt.secao_prazo("2026-11-30T12:00:00Z", False, AGORA) == "proximos"
    assert fmt.secao_prazo("2026-12-20T12:00:00Z", False, AGORA) == "adiante"
    assert fmt.secao_prazo(None, False, AGORA) == "adiante"
    assert fmt.secao_prazo("2026-11-22T12:00:00Z", True, AGORA) == "entregues"


# --------------------------------------------------------------------------
# Tempo desde a última sincronização
# --------------------------------------------------------------------------
def test_ha_quanto_tempo():
    agora = datetime(2026, 11, 25, 13, 0, 0, tzinfo=timezone.utc)
    assert fmt.ha_quanto_tempo("2026-11-25T12:55:00Z", agora) == "há 5 min"
    assert fmt.ha_quanto_tempo("2026-11-25T11:00:00Z", agora) == "há 2 horas"
    assert fmt.ha_quanto_tempo("2026-11-24T13:00:00Z", agora) == "há 1 dia"
    assert fmt.ha_quanto_tempo("2026-11-25T12:59:40Z", agora) == "agora mesmo"
    assert fmt.ha_quanto_tempo(None) == "nunca"


# --------------------------------------------------------------------------
# Números e plural
# --------------------------------------------------------------------------
def test_numero_br():
    assert fmt.numero_br(358) == "358"
    assert fmt.numero_br(1234) == "1.234"
    assert fmt.numero_br(1234567) == "1.234.567"
    assert fmt.numero_br(1234.5) == "1.234,5"
    assert fmt.numero_br(None) == "—"


def test_plural():
    assert fmt.plural(1, "dia") == "1 dia"
    assert fmt.plural(2, "dia") == "2 dias"
    assert fmt.plural(5, "min", "min") == "5 min"
    assert fmt.plural(1, "hora") == "1 hora"


# --------------------------------------------------------------------------
# Nomes legíveis (sem mexer nos dados salvos)
# --------------------------------------------------------------------------
def test_nome_materia_remove_codigo_e_parenteses():
    bruto = "218131 - MÉTODOS DE COMPUTAÇÃO EXPERIMENTAL E QUANTITATIVA (MAT) 0101-06-26-2s"
    assert fmt.nome_materia(bruto) == "Métodos de Computação Experimental e Quantitativa"


def test_nome_materia_sem_codigo_mantem_texto():
    assert fmt.nome_materia("Banco de Dados I") == "Banco de Dados I"


def test_nome_materia_preserva_numeral_romano():
    assert (fmt.nome_materia("PROJETO INTEGRADOR VI - ENGENHARIA DE SOFTWARE PRÁTICA")
            == "Projeto Integrador VI Engenharia de Software Prática")
    assert fmt.nome_materia("CÁLCULO II") == "Cálculo II"


def test_nome_arquivo_legivel():
    assert fmt.nome_arquivo("aula03.pdf") == "Aula 03"
    assert fmt.nome_arquivo("ex_aula_semana6.pdf") == "Ex Aula Semana 6"
    assert fmt.nome_arquivo("lista_exercicios_01.pdf") == "Lista Exercicios 01"


def test_titulo_tarefa_desforca_caixa_alta():
    assert fmt.titulo_tarefa("PROVA FINAL DE BANCO DE DADOS") == "Prova Final de Banco de Dados"
    # Não está todo em maiúsculas: mantém o texto original.
    assert fmt.titulo_tarefa("Entrega_aula03_trabalho") == "Entrega_aula03_trabalho"
