"""Sincroniza só o Agente Canvas (sem Tutor), para todos os cursos ou um --curso.

Uso (a partir da raiz do repositório):
    python scripts/sincronizar.py [--curso ID] [--completo] [--sem-indexar]

Grava data/logs/sync_<data-hora>.json com, por curso: novos, atualizados,
migrados, só registrados, recuperados, pulados (não PDF), falhas, pendentes da
LLM, removidos, contagem por categoria, requisições, MB baixados e tempo.

Sem --sem-indexar, indexa no RAG os cursos que mudaram (ou que ainda não estão
no índice), como o canvas_agent_node.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from src.agente_canvas.service import (  # noqa: E402
    CanvasAuthError,
    CanvasConfigError,
    CanvasService,
)

DIR_LOGS = Path("data/logs")
CAMPOS_LISTA = ("novos", "atualizados", "migrados", "registrados", "recuperados",
                "pulados", "falhas", "pendentes_llm", "bloqueados", "removidos")


def _mb_baixados(caminhos) -> float:
    total = 0
    for c in caminhos:
        try:
            total += Path(c).stat().st_size
        except OSError:
            pass
    return round(total / 1024 / 1024, 2)


def _linha(curso: dict) -> str:
    if curso.get("erro"):
        return f"{curso['course_id']:>7} | ERRO: {curso['erro']}"
    c = curso["contagens"]
    return (f"{curso['course_id']:>7} | {c['novos']:>5} {c['atualizados']:>5} {c['migrados']:>5} "
            f"{c['registrados']:>5} {c['recuperados']:>5} {c['pulados']:>5} {c['falhas']:>5} "
            f"{c['pendentes_llm']:>5} {c['bloqueados']:>5} | {curso['requisicoes']:>4} {curso['mb_baixados']:>8.2f} "
            f"{curso['tempo_s']:>7.1f} | {curso.get('parou_em') or '-'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--curso", type=int, help="sincroniza só este curso")
    parser.add_argument("--completo", action="store_true",
                        help="varredura completa (ignora a parada antecipada)")
    parser.add_argument("--sem-indexar", action="store_true",
                        help="não indexa no RAG depois de sincronizar")
    args = parser.parse_args()

    sys.stdout.reconfigure(errors="replace")
    load_dotenv()
    inicio_total = time.perf_counter()

    try:
        service = CanvasService()
        cursos = service.get_user_courses()
    except CanvasAuthError as e:
        print(f"ERRO: {e}")
        return 1
    req_cursos = service.requisicoes

    if args.curso:
        cursos = [c for c in cursos if c.id == args.curso]
        if not cursos:
            print(f"ERRO: curso {args.curso} não está entre os cursos ativos.")
            return 1

    print(f"{len(cursos)} curso(s); completo={args.completo}; indexar={not args.sem_indexar}")
    resultados = []
    for curso in cursos:
        print(f"\n=== {curso.id} - {curso.name}")
        t0 = time.perf_counter()
        item = {"course_id": curso.id, "nome": curso.name}
        try:
            r = service.sincronizar_curso(curso.id, completo=args.completo)
        except CanvasConfigError:
            raise
        except Exception as e:  # 401 num curso, Canvas fora do ar etc.: segue
            item.update(erro=f"{type(e).__name__}: {e}",
                        tempo_s=round(time.perf_counter() - t0, 1))
            resultados.append(item)
            print(f"  falha: {item['erro']}")
            continue
        item.update(
            contagens={k: len(r[k]) for k in CAMPOS_LISTA},
            listas={k: r[k] for k in CAMPOS_LISTA if r[k]},
            categorias=r["categorias"],
            requisicoes=r["requisicoes"],
            mb_baixados=_mb_baixados(r["baixados"]),
            tempo_s=round(time.perf_counter() - t0, 1),
            parou_em=r["parou_em"],
            mudou=r["mudou"],
            estado_gravado=r["estado_gravado"],
        )

        if not args.sem_indexar:
            from src.rag.indexacao import curso_indexado, indexar_curso
            if r["mudou"] or not curso_indexado(curso.id):
                t1 = time.perf_counter()
                try:
                    ri = indexar_curso(curso.id)
                    item["indexacao"] = {"chunks": ri.get("chunks"), "pulado": ri.get("pulado"),
                                         "aviso": ri.get("aviso"),
                                         "tempo_s": round(time.perf_counter() - t1, 1)}
                except Exception as e:
                    item["indexacao"] = {"erro": str(e)}
        resultados.append(item)
        print("  " + _linha(item))

    ok = [r for r in resultados if not r.get("erro")]
    totais = {k: sum(r["contagens"][k] for r in ok) for k in CAMPOS_LISTA}
    totais.update(requisicoes=sum(r["requisicoes"] for r in ok) + req_cursos,
                  requisicoes_listar_cursos=req_cursos,
                  mb_baixados=round(sum(r["mb_baixados"] for r in ok), 2),
                  tempo_s=round(time.perf_counter() - inicio_total, 1),
                  cursos=len(resultados), cursos_com_erro=len(resultados) - len(ok))

    DIR_LOGS.mkdir(parents=True, exist_ok=True)
    arquivo = DIR_LOGS / f"sync_{datetime.now():%Y%m%d-%H%M%S}.json"
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump({"executado_em": datetime.now().isoformat(timespec="seconds"),
                   "completo": args.completo, "indexar": not args.sem_indexar,
                   "curso": args.curso, "cursos": resultados, "totais": totais},
                  f, ensure_ascii=False, indent=2)

    print("\n  curso | novos atual migr  regs recup pulad falha p_llm bloq |  req       MB   tempo | parou em")
    for r in resultados:
        print("  " + _linha(r))
    print(f"\nTotais: {json.dumps(totais, ensure_ascii=False)}")
    print(f"Log: {arquivo}")
    return 0 if not totais["cursos_com_erro"] and not totais["falhas"] else 2


if __name__ == "__main__":
    sys.exit(main())
