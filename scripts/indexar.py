"""Indexa os PDFs de um curso no ChromaDB (data/chroma/).

Uso (a partir da raiz do repositório):
    python scripts/indexar.py <course_id> [janela] [sobreposicao] [--forcar]

Padrão: janela=1, sobreposicao=0 (coleção rag_j1_s0 = COLECAO_PADRAO, a
consultada por src.rag.buscar). Reindexar substitui os chunks do curso na
coleção, sem duplicar. A reindexação é pulada quando a lista de PDFs e suas
datas de modificação não mudaram; use --forcar para reindexar mesmo assim.
"""

import argparse
import logging
import sys
from pathlib import Path

# Permite "from src.rag ..." ao rodar o script diretamente.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rag.indexacao import indexar_curso, obter_colecao  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("course_id", type=int, help="id do curso no Canvas")
    parser.add_argument("janela", type=int, nargs="?", default=1)
    parser.add_argument("sobreposicao", type=int, nargs="?", default=0)
    parser.add_argument("--forcar", action="store_true",
                        help="reindexa mesmo sem mudanças nos PDFs")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.stdout.reconfigure(errors="replace")
    try:
        r = indexar_curso(args.course_id, args.janela, args.sobreposicao, forcar=args.forcar)
    except ValueError as e:
        parser.error(str(e))

    print(f"Curso {r['course_id']} -> coleção {r['colecao']}")
    print(f"  PDFs:             {r['pdfs']}")
    print(f"  páginas mantidas: {r['paginas_mantidas']}")
    print(f"  chunks:           {r['chunks']}")
    print(f"  tempo:            {r['tempo_s']} s")
    if r.get("pulado"):
        print("  pulado:           sim (PDFs sem mudanças desde a última indexação)")
    if r["aviso"]:
        print(f"  aviso:            {r['aviso']}")
        return 1
    colecao = obter_colecao(r["colecao"])
    print(f"  total na coleção: {colecao.count()} (todos os cursos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
