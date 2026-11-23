"""Testes offline da integração Tutor + RAG (sem LLM e sem Canvas).

Uso (a partir da raiz do repositório):
    python scripts/testar_integracao.py

Valida:
  1. buscar("hipótese nula", 93527) traz aula03 p.15 entre as fontes;
  2. curso sem índice gera a mensagem padrão SEM instanciar/chamar o LLM;
  3. consulta vazia é tratada (ValueError em buscar; ignorada no Tutor);
  4. "import src.graph" funciona.

Não lê o .env nem acessa a rede. Sai com código 0 se tudo passar.
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(errors="replace")

from src.rag import buscar  # noqa: E402

CURSO_INDEXADO = 93527
CURSO_SEM_INDICE = 99999999


def teste_busca_hipotese_nula() -> None:
    trechos = buscar("hipótese nula", CURSO_INDEXADO, k=5)
    fontes = {(t["arquivo"], t["pagina"]) for t in trechos}
    print(f"  fontes: {sorted(fontes)}")
    assert any(
        arq.startswith("aula03") and pag == 15 for arq, pag in fontes
    ), "aula03 p.15 não apareceu entre as fontes de 'hipótese nula'."


def teste_curso_sem_indice_sem_llm() -> None:
    from src.agente_tutor.service import TutorService

    service = TutorService()
    resumo = service.generate_summary_for_course(CURSO_SEM_INDICE, "Curso Inexistente")
    assert resumo.sources_used == [], "Curso sem índice não deveria ter fontes."
    assert "não está indexada" in resumo.summary_text, "Mensagem de não indexado ausente."
    # Prova de que o LLM não foi instanciado nem chamado.
    assert service._llm is None, "O LLM foi instanciado no caminho sem índice."
    print(f"  mensagem: {resumo.summary_text[:70]}...")


def teste_consulta_vazia() -> None:
    from src.agente_tutor.service import TutorService

    for consulta in ("", "   "):
        try:
            buscar(consulta, CURSO_INDEXADO)
        except ValueError:
            pass
        else:
            raise AssertionError(f"buscar({consulta!r}) deveria levantar ValueError.")
    # No Tutor, consultas vazias são apenas ignoradas (não quebram).
    service = TutorService()
    assert service._recuperar_trechos(CURSO_INDEXADO, ["", "   "]) == []
    print("  ValueError em buscar e consultas vazias ignoradas no Tutor.")


def teste_import_graph() -> None:
    importlib.import_module("src.graph")
    print("  import src.graph OK.")


def main() -> int:
    testes = [
        ("1. buscar('hipótese nula', 93527) -> aula03 p.15", teste_busca_hipotese_nula),
        ("2. curso sem índice -> mensagem sem LLM", teste_curso_sem_indice_sem_llm),
        ("3. consulta vazia tratada", teste_consulta_vazia),
        ("4. import src.graph", teste_import_graph),
    ]
    falhas = 0
    for nome, teste in testes:
        print(f"\n[TESTE] {nome}")
        try:
            teste()
            print("  OK")
        except Exception as e:
            falhas += 1
            print(f"  FALHOU: {e}")

    print(f"\n{'='*50}")
    if falhas:
        print(f"{falhas} teste(s) falharam.")
        return 1
    print("Todos os testes passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
