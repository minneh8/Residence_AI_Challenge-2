"""Faz uma busca no índice e mostra os trechos encontrados.

Uso (a partir da raiz do repositório):
    python scripts/testar_busca.py <course_id> "<pergunta>" [k] [--colecao NOME]

Sem --colecao, usa a mesma coleção de buscar() (busca.COLECAO_PADRAO).
Mostra score, arquivo, páginas e um trecho curto de cada resultado.
"""

import argparse
import logging
import sys
from pathlib import Path

# Permite "from src.rag ..." ao rodar o script diretamente.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rag.busca import COLECAO_PADRAO, buscar_na_colecao  # noqa: E402

TAMANHO_TRECHO = 160


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("course_id", type=int, help="id do curso no Canvas")
    parser.add_argument("pergunta")
    parser.add_argument("k", type=int, nargs="?", default=5)
    parser.add_argument("--colecao", default=COLECAO_PADRAO,
                        help=f"coleção do ChromaDB (padrão: {COLECAO_PADRAO})")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.stdout.reconfigure(errors="replace")
    try:
        trechos = buscar_na_colecao(args.pergunta, args.course_id, args.k, args.colecao)
    except ValueError as e:
        print(f"ValueError: {e}")
        return 2

    print(f"[{args.colecao}] curso {args.course_id} | k={args.k} | {args.pergunta!r}")
    if not trechos:
        print("  (nenhum resultado)")
        return 1
    for t in trechos:
        paginas = (f"p.{t['pagina']}" if t["pagina"] == t["pagina_fim"]
                   else f"p.{t['pagina']}-{t['pagina_fim']}")
        trecho = " ".join(t["texto"].split())[:TAMANHO_TRECHO]
        print(f"  {t['score']:.4f}  {t['arquivo']} {paginas}  {trecho}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
