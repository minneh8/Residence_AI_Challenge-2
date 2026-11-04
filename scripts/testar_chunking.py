"""Relatório do chunking dos PDFs de um curso.

Uso (a partir da raiz do repositório):
    python scripts/testar_chunking.py <course_id> [janela] [sobreposicao]

Mostra totais, páginas descartadas, tamanho dos chunks, chunks por PDF e
3 exemplos curtos. Nada é gravado em disco.
"""

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

# Permite "from src.rag ..." ao rodar o script diretamente.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rag.chunking import filtrar_paginas, gerar_chunks  # noqa: E402
from src.rag.extracao import extrair_curso  # noqa: E402

TAMANHO_EXEMPLO = 300


def relatorio(course_id: int, janela: int, sobreposicao: int) -> int:
    paginas = extrair_curso(course_id)
    _, descartadas = filtrar_paginas(paginas)
    chunks = gerar_chunks(paginas, janela=janela, sobreposicao=sobreposicao)

    print(f"Curso {course_id} | janela={janela} sobreposicao={sobreposicao}")
    print(f"  páginas extraídas:   {len(paginas)}")
    print(f"  páginas descartadas: {len(descartadas)}")
    for motivo, n in Counter(d["motivo"] for d in descartadas).items():
        print(f"    {n:3d} por {motivo}")
    for d in descartadas:
        print(f"    - {d['arquivo']} p.{d['pagina']} ({d['motivo']})")
    print(f"  chunks:              {len(chunks)}")
    if not chunks:
        return 1

    tamanhos = [c["caracteres"] for c in chunks]
    print(f"  caracteres por chunk: mín {min(tamanhos)} | "
          f"média {sum(tamanhos) / len(tamanhos):.0f} | máx {max(tamanhos)}")
    print("  chunks por PDF:")
    for arquivo, n in Counter(c["arquivo"] for c in chunks).items():
        print(f"    {arquivo}: {n}")

    ids = [c["chunk_id"] for c in chunks]
    if len(set(ids)) != len(ids):
        print("  ATENÇÃO: chunk_id duplicado!")

    print("  exemplos:")
    for i in sorted({0, len(chunks) // 2, len(chunks) - 1}):
        c = chunks[i]
        trecho = c["texto"][:TAMANHO_EXEMPLO].replace("\n", " / ")
        print(f"    [{c['chunk_id']}] ({c['caracteres']} chars) {trecho}...")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("course_id", type=int, help="id do curso no Canvas")
    parser.add_argument("janela", type=int, nargs="?", default=1)
    parser.add_argument("sobreposicao", type=int, nargs="?", default=0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.stdout.reconfigure(errors="replace")
    try:
        return relatorio(args.course_id, args.janela, args.sobreposicao)
    except ValueError as e:
        parser.error(str(e))


if __name__ == "__main__":
    sys.exit(main())
