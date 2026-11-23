"""Mede o score top-1 do RAG para temas de dentro e de fora de uma disciplina.

Uso (a partir da raiz do projeto, a pasta que tem src/ e prompts/):
    python scripts/medir_scores_temas.py --curso N --dentro "<tema>" ... --fora "<tema>" ...

Para cada tema, chama buscar(tema, curso, k=1) e imprime só o score do trecho
mais parecido, nunca o texto: a ideia é escolher o SCORE_MINIMO do gerador
(src/agente_gerador/service.py) olhando onde os temas de dentro e os de fora
se separam. Precisa da disciplina indexada (rode a esteira com --curso N antes).
"""

import argparse
import sys
from pathlib import Path

# Permite "from src..." ao rodar o script diretamente.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agente_gerador.service import SCORE_MINIMO  # noqa: E402


def medir(temas: list[str], curso: int, buscar) -> list[float | None]:
    """Score top-1 de cada tema; None quando o RAG não devolve nada."""
    scores = []
    for tema in temas:
        trechos = buscar(tema, curso, k=1)
        scores.append(trechos[0]["score"] if trechos else None)
    return scores


def main(argv: list[str] | None = None, buscar=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--curso", type=int, required=True, help="id da disciplina no Canvas")
    parser.add_argument("--dentro", nargs="+", default=[], help="temas que a disciplina cobre")
    parser.add_argument("--fora", nargs="+", default=[], help="temas que a disciplina não cobre")
    args = parser.parse_args(argv)
    if not args.dentro and not args.fora:
        parser.error("informe pelo menos um tema em --dentro ou --fora.")

    if buscar is None:
        from src.rag import buscar  # importa o RAG (e o modelo E5) só quando vai usar

    linhas = [("dentro", tema) for tema in args.dentro] + [("fora", tema) for tema in args.fora]
    scores = medir([tema for _, tema in linhas], args.curso, buscar)
    if all(score is None for score in scores):
        print(f"ERRO: o curso {args.curso} não está indexado.", file=sys.stderr)
        return 2

    print(f"curso {args.curso} | SCORE_MINIMO atual: {SCORE_MINIMO}")
    print(f"{'grupo':<7} {'score':>6}  tema")
    for (grupo, tema), score in zip(linhas, scores):
        texto = "  —   " if score is None else f"{score:6.3f}"
        print(f"{grupo:<7} {texto}  {tema}")

    dentro = [s for (g, _), s in zip(linhas, scores) if g == "dentro" and s is not None]
    fora = [s for (g, _), s in zip(linhas, scores) if g == "fora" and s is not None]
    if dentro and fora:
        print(f"\nmenor de dentro: {min(dentro):.3f} | maior de fora: {max(fora):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
