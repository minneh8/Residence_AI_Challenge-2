"""Relatório da extração de texto dos PDFs de um curso.

Uso (a partir da raiz do repositório):
    python scripts/testar_extracao.py <course_id>

Mostra, por PDF: total de páginas, total de caracteres, média por página,
páginas com pouco texto (possíveis candidatas a OCR) e uma amostra curta.
Nada é gravado em disco.
"""

import argparse
import logging
import sys
from pathlib import Path

# Permite "from src.rag ..." ao rodar o script diretamente.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rag.extracao import extrair_curso, listar_pdfs  # noqa: E402

LIMITE_POUCO_TEXTO = 50   # páginas abaixo disso podem precisar de OCR
TAMANHO_AMOSTRA = 200     # caracteres exibidos por página de amostra
PAGINAS_AMOSTRA = 3


def _amostra(paginas: list[dict]) -> list[dict]:
    """Escolhe até 3 páginas com texto, espalhadas (início, meio, fim)."""
    com_texto = [p for p in paginas if len(p["texto"]) >= LIMITE_POUCO_TEXTO]
    if len(com_texto) <= PAGINAS_AMOSTRA:
        return com_texto
    indices = sorted({0, len(com_texto) // 2, len(com_texto) - 1})
    return [com_texto[i] for i in indices]


def relatorio(course_id: int) -> int:
    pdfs = listar_pdfs(course_id)
    itens = extrair_curso(course_id)

    por_arquivo: dict[str, list[dict]] = {}
    for item in itens:
        por_arquivo.setdefault(item["arquivo"], []).append(item)

    print(f"Curso {course_id}: {len(pdfs)} PDF(s) em data/raw/{course_id}/\n")
    falhas = 0
    for pdf in pdfs:
        print("=" * 72)
        print(pdf.name)
        paginas = por_arquivo.get(pdf.name)
        if not paginas:
            falhas += 1
            print("  FALHOU ou sem páginas (ver log acima)")
            continue

        total_chars = sum(len(p["texto"]) for p in paginas)
        poucas = [p["pagina"] for p in paginas if len(p["texto"]) < LIMITE_POUCO_TEXTO]
        print(f"  páginas:              {len(paginas)}")
        print(f"  caracteres:           {total_chars}")
        print(f"  média por página:     {total_chars / len(paginas):.0f}")
        print(f"  páginas < {LIMITE_POUCO_TEXTO} chars:    {len(poucas)}"
              + (f" -> {poucas}" if poucas else ""))
        for p in _amostra(paginas):
            trecho = p["texto"][:TAMANHO_AMOSTRA].replace("\n", " / ")
            print(f"  [p.{p['pagina']}] {trecho}...")
    print("=" * 72)
    print(f"Total: {len(itens)} páginas extraídas, {falhas} PDF(s) com falha.")
    return 1 if falhas else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("course_id", type=int, help="id do curso no Canvas")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    # Evita erro ao imprimir caracteres que o console do Windows não suporta.
    sys.stdout.reconfigure(errors="replace")
    return relatorio(args.course_id)


if __name__ == "__main__":
    sys.exit(main())
