"""Avalia a recuperação de trechos nas coleções do ChromaDB.

Uso (a partir da raiz do repositório):
    python scripts/avaliar.py [--incluir-sugeridas] [--categorias slides ...]
                              [--colecoes rag_j1_s0 ...]

Lê avaliacao/perguntas.json e, para cada coleção e cada k em KS, consulta
buscar_na_colecao. Por padrão usa só perguntas com status "confirmada";
--incluir-sugeridas também usa as de status "sugerida". --categorias filtra a
busca pelas categorias do Agente Canvas (metadata "categoria" dos chunks).

Trecho relevante: mesmo arquivo de uma resposta aceita e intervalo
pagina..pagina_fim cobrindo alguma página esperada dela.

Métricas (perguntas com resposta, média por pergunta), no total e por tipo:
  HitRate@k    fração de perguntas com pelo menos um trecho relevante no top-k
               (antes chamada de "Recall@k" neste script);
  Recall@k     páginas relevantes recuperadas / total de páginas relevantes da
               pergunta (pares arquivo+página do gabarito);
  Precision@k  trechos relevantes / k;
  MRR          1 / posição do primeiro trecho relevante (0 se não houver);
  páginas/resultado  média de páginas cobertas por trecho.
Para perguntas "fora", compara o maior score de cada uma com o maior score das
perguntas com resposta.

Acrescenta um resumo ao final de avaliacao/resultados.md, sem trechos dos PDFs.
"""

import argparse
import json
import logging
import statistics
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
# Permite "from src.rag ..." ao rodar o script diretamente.
sys.path.insert(0, str(RAIZ))

from src.rag.busca import buscar_na_colecao  # noqa: E402

ARQ_PERGUNTAS = RAIZ / "avaliacao" / "perguntas.json"
ARQ_RESULTADOS = RAIZ / "avaliacao" / "resultados.md"
COLECOES = ["rag_j1_s0", "rag_j3_s1"]
KS = [3, 5]
MINIMO_CONCLUSIVO = 5


def carregar_perguntas(incluir_sugeridas: bool) -> list[dict]:
    status_aceitos = {"confirmada", "sugerida"} if incluir_sugeridas else {"confirmada"}
    perguntas = json.loads(ARQ_PERGUNTAS.read_text(encoding="utf-8"))
    return [p for p in perguntas if p.get("status") in status_aceitos]


def eh_acerto(trecho: dict, respostas: list[dict]) -> bool:
    """Trecho relevante: mesmo arquivo e cobre alguma página esperada."""
    return any(
        trecho["arquivo"] == r["arquivo"]
        and any(trecho["pagina"] <= p <= trecho["pagina_fim"] for p in r["paginas"])
        for r in respostas
    )


def posicao_acerto(trechos: list[dict], respostas: list[dict]) -> int | None:
    """Posição (1-based) do primeiro resultado correto, ou None."""
    for i, t in enumerate(trechos, start=1):
        if eh_acerto(t, respostas):
            return i
    return None


def recall_paginas(trechos: list[dict], respostas: list[dict]) -> float:
    """Páginas relevantes (arquivo, página) cobertas por algum trecho / total."""
    relevantes = {(r["arquivo"], p) for r in respostas for p in r["paginas"]}
    if not relevantes:
        return 0.0
    recuperadas = {
        (arq, p) for arq, p in relevantes
        if any(t["arquivo"] == arq and t["pagina"] <= p <= t["pagina_fim"] for t in trechos)
    }
    return len(recuperadas) / len(relevantes)


def precisao(trechos: list[dict], respostas: list[dict], k: int) -> float:
    """Trechos relevantes / k (o denominador é k mesmo se vierem menos trechos)."""
    return sum(eh_acerto(t, respostas) for t in trechos) / k


def paginas_cobertas(t: dict) -> int:
    return t["pagina_fim"] - t["pagina"] + 1


def fmt_paginas(t: dict) -> str:
    return f"p.{t['pagina']}" if t["pagina"] == t["pagina_fim"] else f"p.{t['pagina']}-{t['pagina_fim']}"


def resumir(itens: list[dict]) -> dict:
    """itens: linhas de perguntas com resposta (ver avaliar)."""
    n = len(itens)
    if n == 0:
        return {"n": 0, "hitrate": None, "recall": None, "precision": None,
                "mrr": None, "paginas": None}
    paginas = [paginas_cobertas(t) for it in itens for t in it["trechos"]]
    return {
        "n": n,
        "hitrate": sum(it["pos"] is not None for it in itens) / n,
        "recall": statistics.mean(it["recall"] for it in itens),
        "precision": statistics.mean(it["precision"] for it in itens),
        "mrr": sum(1 / it["pos"] for it in itens if it["pos"] is not None) / n,
        "paginas": statistics.mean(paginas) if paginas else None,
    }


def avaliar(perguntas: list[dict], colecoes: list[str], categorias=None) -> dict:
    """Retorna resultados[colecao][k] = lista de dicts por pergunta."""
    resultados: dict = {}
    for colecao in colecoes:
        resultados[colecao] = {}
        for k in KS:
            linhas = []
            for p in perguntas:
                trechos = buscar_na_colecao(p["pergunta"], p["course_id"], k, colecao, categorias)
                respostas = p["respostas"]
                linhas.append({
                    "pergunta": p,
                    "trechos": trechos,
                    "pos": posicao_acerto(trechos, respostas) if respostas else None,
                    "recall": recall_paginas(trechos, respostas) if respostas else None,
                    "precision": precisao(trechos, respostas, k) if respostas else None,
                    "maior_score": trechos[0]["score"] if trechos else None,
                })
            resultados[colecao][k] = linhas
    return resultados


def num(v, casas: int = 3) -> str:
    return "-" if v is None else f"{v:.{casas}f}"


def montar_relatorio(perguntas: list[dict], resultados: dict, incluir_sugeridas: bool,
                     colecoes: list[str], categorias=None) -> tuple[str, str]:
    """Retorna (texto para o terminal, seção markdown para resultados.md)."""
    com_resposta = [p for p in perguntas if p["respostas"]]
    fora = [p for p in perguntas if p["tipo"] == "fora"]
    tipos = sorted({p["tipo"] for p in com_resposta})
    colunas = [(c, k) for c in colecoes for k in KS]
    cab = "| Métrica | " + " | ".join(f"{c} k={k}" for c, k in colunas) + " |"
    sep = "|---|" + "---|" * len(colunas)

    md: list[str] = []
    agora = datetime.now().strftime("%Y-%m-%d %H:%M")
    md.append(f"### Rodada {agora}")
    md.append("")
    md.append(f"- Coleções: {', '.join(colecoes)}")
    md.append(f"- k: {', '.join(map(str, KS))}")
    md.append(f"- Filtro de categorias: {', '.join(categorias) if categorias else 'nenhum (todas)'}")
    md.append(f"- Perguntas usadas: {len(perguntas)} "
              f"({len(com_resposta)} com resposta, {len(fora)} do tipo \"fora\")")
    md.append(f"- Sugeridas incluídas: {'sim' if incluir_sugeridas else 'não'}")
    md.append("- Relevante: mesmo arquivo de uma resposta aceita e pagina <= p <= pagina_fim "
              "para alguma página esperada. Métricas: média por pergunta.")
    if len(perguntas) < MINIMO_CONCLUSIVO or len(com_resposta) < MINIMO_CONCLUSIVO:
        md.append(f"- **Aviso:** menos de {MINIMO_CONCLUSIVO} perguntas usadas; "
                  "resultado não conclusivo.")
    if incluir_sugeridas:
        md.append("- **Prévia:** inclui perguntas ainda não confirmadas.")
    md.append("")

    # Métricas gerais e por tipo.
    md.append("#### Perguntas com resposta")
    md.append("")
    md.append(cab)
    md.append(sep)
    grupos = [("Total", com_resposta)] + [(f"tipo {t}", [p for p in com_resposta if p["tipo"] == t])
                                         for t in tipos]
    for rotulo, grupo in grupos:
        ids = {p["id"] for p in grupo}
        resumos = [resumir([l for l in resultados[c][k] if l["pergunta"]["id"] in ids])
                   for c, k in colunas]
        n = resumos[0]["n"]
        md.append(f"| **{rotulo}** (n={n}) HitRate@k | " + " | ".join(num(r["hitrate"]) for r in resumos) + " |")
        md.append(f"| {rotulo} Recall@k | " + " | ".join(num(r["recall"]) for r in resumos) + " |")
        md.append(f"| {rotulo} Precision@k | " + " | ".join(num(r["precision"]) for r in resumos) + " |")
        md.append(f"| {rotulo} MRR | " + " | ".join(num(r["mrr"]) for r in resumos) + " |")
        md.append(f"| {rotulo} páginas/resultado | " + " | ".join(num(r["paginas"], 2) for r in resumos) + " |")
    md.append("")

    # Perguntas fora do escopo: maior score (independe de k; usa o maior k).
    k_max = max(KS)
    md.append(f"#### Maior score: \"fora\" × com resposta (top-1, k={k_max})")
    md.append("")
    md.append("| Pergunta | " + " | ".join(colecoes) + " |")
    md.append("|---|" + "---|" * len(colecoes))
    por_id = {c: {l["pergunta"]["id"]: l for l in resultados[c][k_max]} for c in colecoes}
    for p in fora:
        md.append(f"| {p['id']} fora: {p['pergunta']} | "
                  + " | ".join(num(por_id[c][p["id"]]["maior_score"], 4) for c in colecoes) + " |")
    for rotulo, func in (("mín", min), ("média", statistics.mean), ("máx", max)):
        valores = []
        for c in colecoes:
            scores = [por_id[c][p["id"]]["maior_score"] for p in com_resposta
                      if por_id[c][p["id"]]["maior_score"] is not None]
            valores.append(func(scores) if scores else None)
        md.append(f"| com resposta ({rotulo}) | " + " | ".join(num(v, 4) for v in valores) + " |")
    md.append("")

    # Erros por coleção e k (sem texto dos PDFs: só arquivo, páginas e score).
    md.append("#### Perguntas que erraram")
    md.append("")
    for c, k in colunas:
        erros = [l for l in resultados[c][k] if l["pergunta"]["respostas"] and l["pos"] is None]
        md.append(f"- **{c} k={k}** ({len(erros)} erro(s))")
        for l in erros:
            p = l["pergunta"]
            if l["trechos"]:
                t = l["trechos"][0]
                primeiro = f"{t['arquivo']} {fmt_paginas(t)} (score {t['score']:.4f})"
            else:
                primeiro = "(nenhum resultado)"
            md.append(f"  - {p['id']} [{p['tipo']}] {p['pergunta']} → 1º: {primeiro}")
    md.append("")

    texto_md = "\n".join(md)
    terminal = texto_md.replace("**", "")
    return terminal, texto_md


def salvar(secao: str) -> None:
    atual = ARQ_RESULTADOS.read_text(encoding="utf-8") if ARQ_RESULTADOS.exists() else ""
    if atual and not atual.endswith("\n"):
        atual += "\n"
    ARQ_RESULTADOS.write_text(atual + "\n" + secao, encoding="utf-8")


def _lista(valores) -> list[str] | None:
    """Aceita "--categorias slides listas" e "--categorias slides,listas"."""
    if not valores:
        return None
    return [v.strip() for item in valores for v in item.split(",") if v.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--incluir-sugeridas", action="store_true",
                        help='inclui perguntas com status "sugerida" (padrão: só "confirmada")')
    parser.add_argument("--categorias", nargs="+", default=None,
                        help="filtra a busca por categoria (ex.: slides, ou slides listas)")
    parser.add_argument("--colecoes", nargs="+", default=None,
                        help=f"coleções avaliadas (padrão: {' '.join(COLECOES)})")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.stdout.reconfigure(errors="replace")

    categorias = _lista(args.categorias)
    colecoes = _lista(args.colecoes) or COLECOES
    perguntas = carregar_perguntas(args.incluir_sugeridas)
    if not perguntas:
        print("Nenhuma pergunta selecionada em perguntas.json.")
        return 1
    com_resposta = sum(1 for p in perguntas if p["respostas"])
    if len(perguntas) < MINIMO_CONCLUSIVO or com_resposta < MINIMO_CONCLUSIVO:
        print(f"AVISO: menos de {MINIMO_CONCLUSIVO} perguntas usadas "
              f"({len(perguntas)} no total, {com_resposta} com resposta). "
              "O resultado não é conclusivo.\n")

    resultados = avaliar(perguntas, colecoes, categorias)
    terminal, secao = montar_relatorio(perguntas, resultados, args.incluir_sugeridas,
                                       colecoes, categorias)
    print(terminal)
    salvar(secao)
    print(f"Resumo acrescentado a {ARQ_RESULTADOS.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
