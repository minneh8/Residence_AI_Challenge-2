"""Testes do script scripts/testar_gerador.py, com LLM falso e sem rede."""

import importlib.util
import json
from pathlib import Path

import pytest
from dubles_gerador import LLMFalso, questao_dissertativa, questao_multipla, resposta
from src.agente_gerador.service import selecionar_trechos

GLAUX = Path(__file__).resolve().parents[2]
SCRIPT = GLAUX / "scripts" / "testar_gerador.py"
EXEMPLO = GLAUX / "scripts" / "trechos_exemplo.json"


def carregar_script():
    """Importa o script pelo caminho (scripts/ não é um pacote Python)."""
    spec = importlib.util.spec_from_file_location("testar_gerador", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def trechos_exemplo() -> list[dict]:
    with EXEMPLO.open(encoding="utf-8") as arquivo:
        return json.load(arquivo)


def resposta_com_duas_questoes():
    primeiro, segundo = trechos_exemplo()[:2]
    return resposta(questao_multipla(1, primeiro), questao_dissertativa(2, segundo))


def test_trechos_de_exemplo_estao_no_formato_do_rag():
    trechos = trechos_exemplo()
    assert len(trechos) == 5
    for trecho in trechos:
        assert set(trecho) == {"texto", "arquivo", "pagina", "score"}
        assert isinstance(trecho["pagina"], int)
        assert trecho["pagina"] >= 1
        assert trecho["texto"].strip()
    assert len(selecionar_trechos(trechos)) == 5  # todos acima do limiar e sem repetição


def test_script_mostra_as_questoes(capsys):
    llm = LLMFalso(resposta_com_duas_questoes())
    argumentos = ["overfitting", "--trechos", str(EXEMPLO), "--quantidade", "2"]
    codigo = carregar_script().main(argumentos, chamar_llm=llm)
    saida = capsys.readouterr().out
    assert codigo == 0
    assert "status: ok" in saida
    assert "* B)" in saida  # a alternativa correta aparece marcada
    assert "fonte: aula_exemplo_01.pdf, p. 3" in saida
    assert len(llm.chamadas) == 1


def test_script_em_json(capsys):
    llm = LLMFalso(resposta_com_duas_questoes())
    argumentos = ["overfitting", "--trechos", str(EXEMPLO), "--quantidade", "2", "--json"]
    carregar_script().main(argumentos, chamar_llm=llm)
    resultado = json.loads(capsys.readouterr().out)
    assert resultado["status"] == "ok"
    assert [q["id"] for q in resultado["questoes"]] == ["q1", "q2"]


def test_script_sem_material_nao_chama_o_llm(capsys, tmp_path):
    fracos = tmp_path / "trechos_fracos.json"
    conteudo = [{**t, "score": 0.3} for t in trechos_exemplo()]
    fracos.write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")
    llm = LLMFalso()
    codigo = carregar_script().main(["overfitting", "--trechos", str(fracos)], chamar_llm=llm)
    assert codigo == 1
    assert "status: sem_material" in capsys.readouterr().out
    assert llm.chamadas == []


def test_quantidade_invalida_mostra_o_erro_do_argparse(capsys):
    argumentos = ["overfitting", "--trechos", str(EXEMPLO), "--quantidade", "11"]
    with pytest.raises(SystemExit) as saida:
        carregar_script().main(argumentos, chamar_llm=LLMFalso())
    assert saida.value.code == 2
    assert "quantidade" in capsys.readouterr().err


def test_sem_chave_avisa_onde_preencher(capsys):
    def sem_chave(mensagens):
        raise RuntimeError("GROQ_API_KEY não encontrada. Crie o arquivo .env na raiz do projeto.")

    argumentos = ["overfitting", "--trechos", str(EXEMPLO)]
    codigo = carregar_script().main(argumentos, chamar_llm=sem_chave)
    assert codigo == 2
    assert "GROQ_API_KEY" in capsys.readouterr().err


def test_rag_sem_dependencias_sugere_os_trechos_de_exemplo(capsys):
    script = carregar_script()

    def rag_sem_chromadb(pergunta, course_id, k=5):
        raise ModuleNotFoundError("No module named 'chromadb'")

    script.buscar_no_rag = rag_sem_chromadb
    codigo = script.main(["overfitting", "--quantidade", "2"], chamar_llm=LLMFalso())
    erro = capsys.readouterr().err
    assert codigo == 2
    assert "chromadb" in erro
    assert "--trechos" in erro
