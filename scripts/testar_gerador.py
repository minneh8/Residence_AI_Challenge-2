"""Gera questões de estudo com o Agente Gerador de Questões e mostra na tela.

Uso (a partir da raiz do projeto, a pasta que tem src/ e prompts/):
    python scripts/testar_gerador.py "<tema>" [--trechos arquivo.json] [--quantidade N]
        [--tipos multipla_escolha dissertativa] [--course-id N] [--json]

Chama o Groq de verdade: precisa de GROQ_API_KEY no .env da raiz do projeto.
Com --trechos, usa os trechos do arquivo JSON no lugar do RAG, por exemplo
scripts/trechos_exemplo.json. Sem --trechos, usa o buscar() do RAG, que precisa
das dependências do requirements.txt e da disciplina indexada (scripts/indexar.py);
se ela não estiver indexada, o resultado é "sem_material".
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Permite "from src..." e "from prompts..." ao rodar o script diretamente.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agente_gerador import service  # noqa: E402
from src.agente_gerador.models import QuestaoMultiplaEscolha, ResultadoGeracao  # noqa: E402
from src.rag import buscar as buscar_no_rag  # noqa: E402

TAMANHO_FONTE = 160  # caracteres do trecho mostrados em cada questão


def carregar_trechos(caminho: Path) -> list[dict]:
    """Lê uma lista de trechos no formato do buscar(): texto, arquivo, pagina, score."""
    with caminho.open(encoding="utf-8") as arquivo:
        trechos = json.load(arquivo)
    if not isinstance(trechos, list) or not all(isinstance(t, dict) for t in trechos):
        raise ValueError(f"{caminho} deve conter uma lista de trechos")
    return trechos


def buscar_no_arquivo(trechos: list[dict]):
    """RAG de mentira: devolve os k trechos de maior score do arquivo."""

    def buscar(pergunta: str, course_id: int, k: int = 5) -> list[dict]:
        ordenados = sorted(trechos, key=lambda t: t["score"], reverse=True)
        return [dict(t) for t in ordenados[:k]]

    return buscar


def mostrar(resultado: ResultadoGeracao) -> None:
    """Imprime o resultado de um jeito fácil de ler."""
    print(f"status: {resultado.status}")
    if resultado.mensagem:
        print(f"mensagem para o aluno: {resultado.mensagem}")
    for questao in resultado.questoes:
        print()
        print(f"[{questao.id}] {questao.tipo} | assunto: {questao.assunto}")
        print(f"  {questao.enunciado}")
        if isinstance(questao, QuestaoMultiplaEscolha):
            for letra, texto in questao.alternativas.items():
                marca = "*" if letra == questao.correta else " "
                print(f"   {marca} {letra}) {texto}")
        ref = questao.trecho_referencia
        resumo = ref.texto if len(ref.texto) <= TAMANHO_FONTE else ref.texto[:TAMANHO_FONTE] + "..."
        print(f"  fonte: {ref.arquivo}, p. {ref.pagina}: {resumo}")


def main(argv: list[str] | None = None, chamar_llm=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tema", help="assunto das questões (entre aspas se tiver espaço)")
    parser.add_argument(
        "--trechos", type=Path, help="arquivo JSON com trechos, no lugar do RAG"
    )
    parser.add_argument(
        "--quantidade", type=int, default=5, help=f"de 1 a {service.TETO_QUESTOES} (padrão: 5)"
    )
    parser.add_argument(
        "--tipos",
        nargs="+",
        choices=service.TIPOS_VALIDOS,
        default=list(service.TIPOS_VALIDOS),
        help="tipos de questão (padrão: os dois)",
    )
    parser.add_argument(
        "--course-id", type=int, default=1, help="id da disciplina no Canvas, usado pelo RAG"
    )
    parser.add_argument("--json", action="store_true", help="mostra o resultado completo em JSON")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="AVISO %(name)s: %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        if args.trechos:
            buscar = buscar_no_arquivo(carregar_trechos(args.trechos))
            origem = str(args.trechos)
        else:
            buscar, origem = buscar_no_rag, f"RAG, disciplina {args.course_id}"
        print(
            f'Gerando {args.quantidade} questões sobre "{args.tema}" ({origem})...',
            file=sys.stderr,
        )
        resultado = service.gerar_questoes(
            args.tema,
            args.course_id,
            args.quantidade,
            args.tipos,
            buscar=buscar,
            chamar_llm=chamar_llm or service.chamar_groq,
        )
    except ImportError as erro:
        print(
            f"ERRO: a busca no RAG precisa das dependências do requirements.txt ({erro}). "
            "Para testar sem o RAG, use --trechos scripts/trechos_exemplo.json.",
            file=sys.stderr,
        )
        return 2
    except (ValueError, OSError) as erro:
        parser.error(str(erro))
    except RuntimeError as erro:
        if "GROQ_API_KEY" not in str(erro):
            raise
        print(f"ERRO: {erro}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(resultado.model_dump(), ensure_ascii=False, indent=2))
    else:
        mostrar(resultado)
    return 0 if resultado.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
