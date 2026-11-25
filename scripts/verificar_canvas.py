"""Verificação de integridade dos PDFs baixados pelo Agente Canvas.

Uso (a partir da raiz do repositório):
    python scripts/verificar_canvas.py [--curso ID] [--sem-canvas]
    python scripts/verificar_canvas.py [--curso ID] --snapshot <arquivo.json>
    python scripts/verificar_canvas.py --comparar <a.json> <b.json>

Checagens, por curso (data/raw/<id>/):
  1. id_em_dois_caminhos   o mesmo id do Canvas em mais de um arquivo no disco
  2. sha256_duplicado      o mesmo conteúdo em dois caminhos
  3. nome_em_categorias    o mesmo nome em mais de uma categoria (subpasta)
  4. catalogo_sem_arquivo  entrada do catálogo sem arquivo no disco
     pdf_fora_catalogo     PDF no disco que o catálogo não conhece
  5. tamanho_divergente    tamanho no disco diferente do size do Canvas
  6. temporarios           .part/.tmp esquecidos
  7. canvas_fora_catalogo  PDFs listados no Canvas que não estão no catálogo
                           (consulta o Canvas; pule com --sem-canvas)

Sai com código 1 se alguma checagem encontrar problema.
"""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agente_canvas.catalogo import NOME_CATALOGO, ler_json  # noqa: E402

RAW = Path("data/raw")
CHECAGENS = ("id_em_dois_caminhos", "sha256_duplicado", "nome_em_categorias",
             "catalogo_sem_arquivo", "pdf_fora_catalogo", "tamanho_divergente",
             "temporarios", "canvas_fora_catalogo")


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _cursos(curso):
    if curso:
        return [RAW / str(curso)]
    return sorted((p for p in RAW.iterdir() if p.is_dir() and p.name.isdigit()),
                  key=lambda p: int(p.name)) if RAW.exists() else []


def _pdfs(pasta: Path):
    return sorted(p for p in pasta.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")


def _pdfs_canvas(service, course_id: int) -> dict:
    """{file_id: (display_name, bloqueado)} dos PDFs listados no Canvas.

    bloqueado = locked_for_user (ex.: módulo não publicado; o aluno não baixa).
    """
    course = service._com_retentativas(lambda: service.canvas.get_course(course_id),
                                       f"abrir o curso {course_id}")
    pdfs = {}
    for a in service._iterar_paginado(lambda: course.get_files(),
                                      f"listar os arquivos do curso {course_id}"):
        nome = getattr(a, "display_name", None) or a.filename
        if nome.lower().endswith(".pdf"):
            pdfs[str(a.id)] = (nome, getattr(a, "locked_for_user", False) is True)
    return pdfs


def verificar_curso(pasta: Path, service=None) -> dict:
    cat = ler_json(pasta / NOME_CATALOGO, {})
    pdfs = _pdfs(pasta)
    rel = {p: p.relative_to(pasta).as_posix() for p in pdfs}
    achados = {k: [] for k in CHECAGENS}

    # 1. mesmo id em dois caminhos: o caminho do catálogo + cópias com o mesmo
    # nome_local em outra categoria ou com o sufixo _<id>.
    for fid, e in cat.items():
        nome_local = (e.get("nome_local") or "").lower()
        stem_sufixo = f"_{fid}.pdf"
        caminhos = {e.get("caminho", "").lower()} if (pasta / e.get("caminho", "")).is_file() else set()
        for p, r in rel.items():
            n = p.name.lower()
            if n == nome_local or n.endswith(stem_sufixo):
                caminhos.add(r.lower())
        if len(caminhos) > 1:
            achados["id_em_dois_caminhos"].append({"id": fid, "caminhos": sorted(caminhos)})

    # 2. mesmo conteúdo em dois caminhos
    por_hash = defaultdict(list)
    for p, r in rel.items():
        por_hash[_sha256(p)].append(r)
    for h, rs in por_hash.items():
        if len(rs) > 1:
            achados["sha256_duplicado"].append({"sha256": h[:16], "caminhos": rs})

    # 3. mesmo nome em mais de uma categoria
    por_nome = defaultdict(set)
    for p, r in rel.items():
        categoria = r.split("/")[0] if "/" in r else "(raiz)"
        por_nome[p.name.lower()].add(categoria)
    for nome, cats in por_nome.items():
        if len(cats) > 1:
            achados["nome_em_categorias"].append({"nome": nome, "categorias": sorted(cats)})

    # 4. catálogo × disco
    caminhos_cat = {e.get("caminho", "").lower() for e in cat.values()}
    for fid, e in cat.items():
        if not (pasta / e.get("caminho", "")).is_file():
            achados["catalogo_sem_arquivo"].append({"id": fid, "caminho": e.get("caminho")})
    for r in rel.values():
        if r.lower() not in caminhos_cat:
            achados["pdf_fora_catalogo"].append(r)

    # 5. tamanho no disco × size do Canvas
    for fid, e in cat.items():
        p = pasta / e.get("caminho", "")
        if p.is_file() and e.get("size") is not None and p.stat().st_size != e["size"]:
            achados["tamanho_divergente"].append(
                {"id": fid, "caminho": e["caminho"], "disco": p.stat().st_size, "canvas": e["size"]})

    # 6. temporários esquecidos
    achados["temporarios"] = sorted(p.relative_to(pasta).as_posix() for p in pasta.rglob("*")
                                    if p.is_file() and p.suffix in (".part", ".tmp"))

    # 7. PDFs do Canvas fora do catálogo
    resultado = {"course_id": int(pasta.name), "pdfs_disco": len(pdfs), "catalogo": len(cat)}
    if service is not None:
        try:
            canvas = _pdfs_canvas(service, int(pasta.name))
            resultado["pdfs_canvas"] = len(canvas)
            achados["canvas_fora_catalogo"] = sorted(
                f"{n} ({fid})" for fid, (n, bloq) in canvas.items() if fid not in cat and not bloq)
            # Informativo (não é problema): bloqueados para o aluno e fora do catálogo.
            resultado["bloqueados_no_canvas"] = sorted(
                f"{n} ({fid})" for fid, (n, bloq) in canvas.items() if fid not in cat and bloq)
        except Exception as e:
            resultado["erro_canvas"] = f"{type(e).__name__}: {e}"
    resultado["achados"] = achados
    resultado["problemas"] = sum(len(v) for v in achados.values())
    return resultado


def snapshot(curso, arquivo: Path) -> None:
    dados = {}
    for pasta in _cursos(curso):
        for p in _pdfs(pasta):
            st = p.stat()
            dados[p.relative_to(RAW).as_posix()] = {
                "sha256": _sha256(p), "mtime_ns": st.st_mtime_ns, "size": st.st_size}
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    print(f"Snapshot com {len(dados)} PDF(s) salvo em {arquivo}")


def comparar(a: Path, b: Path) -> int:
    sa = json.loads(a.read_text(encoding="utf-8"))
    sb = json.loads(b.read_text(encoding="utf-8"))
    novos = sorted(set(sb) - set(sa))
    sumiram = sorted(set(sa) - set(sb))
    conteudo = sorted(k for k in set(sa) & set(sb) if sa[k]["sha256"] != sb[k]["sha256"])
    so_mtime = sorted(k for k in set(sa) & set(sb)
                      if sa[k]["sha256"] == sb[k]["sha256"] and sa[k]["mtime_ns"] != sb[k]["mtime_ns"])
    print(f"Comparando {a} ({len(sa)}) x {b} ({len(sb)})")
    for titulo, lista in (("novos", novos), ("sumiram", sumiram),
                          ("conteúdo mudou", conteudo), ("só o mtime mudou", so_mtime)):
        print(f"  {titulo}: {len(lista)}")
        for k in lista:
            print(f"    - {k}")
    mudou = len(novos) + len(sumiram) + len(conteudo) + len(so_mtime)
    print("  => nenhum arquivo mudou" if not mudou else f"  => {mudou} arquivo(s) mudaram")
    return 1 if mudou else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--curso", type=int)
    parser.add_argument("--sem-canvas", action="store_true",
                        help="não consulta o Canvas (pula a checagem 7)")
    parser.add_argument("--snapshot", type=Path, metavar="ARQUIVO")
    parser.add_argument("--comparar", type=Path, nargs=2, metavar=("A", "B"))
    parser.add_argument("--json", type=Path, help="grava o resultado completo neste arquivo")
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")

    if args.comparar:
        return comparar(*args.comparar)
    if args.snapshot:
        snapshot(args.curso, args.snapshot)
        return 0

    service = None
    if not args.sem_canvas:
        from dotenv import load_dotenv
        from src.agente_canvas.service import CanvasService
        load_dotenv()
        service = CanvasService()

    resultados = [verificar_curso(p, service) for p in _cursos(args.curso)]
    abrev = ("id2", "sha", "nome", "cat-", "disc-", "tam", "tmp", "canv")
    print("\n  curso | disco catál canvas | " + " ".join(f"{a:>5}" for a in abrev) + " | total")
    for r in resultados:
        a = r["achados"]
        print(f"{r['course_id']:>7} | {r['pdfs_disco']:>5} {r['catalogo']:>5} "
              f"{str(r.get('pdfs_canvas', '-')):>6} | "
              + " ".join(f"{len(a[k]):>5}" for k in CHECAGENS) + f" | {r['problemas']:>5}"
              + (f"  ERRO canvas: {r['erro_canvas']}" if r.get("erro_canvas") else ""))
        for k in CHECAGENS:
            for item in a[k]:
                print(f"      [{k}] {item}")
        for item in r.get("bloqueados_no_canvas", []):
            print(f"      (info) bloqueado para o aluno, fora do catálogo: {item}")
    total = sum(r["problemas"] for r in resultados)
    erros = sum(1 for r in resultados if r.get("erro_canvas"))
    print(f"\nTotal de problemas: {total}" + (f"; {erros} curso(s) sem consulta ao Canvas" if erros else ""))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if total or erros else 0


if __name__ == "__main__":
    sys.exit(main())
