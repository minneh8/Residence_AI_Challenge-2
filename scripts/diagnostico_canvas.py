"""Diagnóstico SOMENTE LEITURA dos arquivos de um curso no Canvas.

Uso (a partir da raiz do repositório):
    python scripts/diagnostico_canvas.py --curso <course_id>

Usa o mesmo cliente do Agente Canvas (CanvasService) e as mesmas variáveis
de ambiente (CANVAS_API_URL, CANVAS_API_KEY). Não baixa arquivos e não
escreve em data/raw/; grava apenas data/logs/diagnostico_<curso>.json.

Mostra:
  - id do usuário atual;
  - pastas do curso (full_name);
  - arquivos (id, display_name, content-type, size, created_at, updated_at,
    pasta e módulo onde aparecem);
  - se course.get_files aceita sort="created_at"/order="desc" e se a primeira
    página já vem com os arquivos mais recentes;
  - número de requisições HTTP feitas (total e por etapa).

O token nunca é impresso nem salvo. As URLs de download dos arquivos (que
carregam um "verifier") também não são salvas.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(errors="replace")

from canvasapi.exceptions import Forbidden, ResourceDoesNotExist, Unauthorized  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from src.agente_canvas.service import CanvasAuthError, CanvasService  # noqa: E402

DIR_LOGS = Path(__file__).resolve().parents[1] / "data" / "logs"

# Parâmetros de query que nunca devem ir para o log.
_PARAMS_SENSIVEIS = {"access_token", "verifier", "token"}


# ------------------------------------------------------------------------------
# Contador de requisições HTTP (hook na sessão requests do canvasapi)
# ------------------------------------------------------------------------------
class ContadorHTTP:
    def __init__(self):
        self.registros: list[dict] = []
        self.etapa = "inicio"

    def hook(self, resposta, *args, **kwargs):
        url = urlparse(resposta.request.url)
        params = {
            k: v for k, v in parse_qsl(url.query) if k not in _PARAMS_SENSIVEIS
        }
        itens = None
        try:
            corpo = resposta.json()
            if isinstance(corpo, list):
                itens = len(corpo)
        except ValueError:
            pass
        self.registros.append({
            "etapa": self.etapa,
            "metodo": resposta.request.method,
            "caminho": url.path,
            "params": params,
            "status": resposta.status_code,
            "itens": itens,
        })
        return resposta

    @property
    def total(self) -> int:
        return len(self.registros)

    def por_etapa(self) -> dict:
        return dict(Counter(r["etapa"] for r in self.registros))


def _instalar_contador(service: CanvasService) -> ContadorHTTP:
    contador = ContadorHTTP()
    sessao = service.canvas._Canvas__requester._session
    sessao.hooks.setdefault("response", []).append(contador.hook)
    return contador


# ------------------------------------------------------------------------------
# Coleta
# ------------------------------------------------------------------------------
def _atrib(obj, nome, padrao=None):
    return getattr(obj, nome, padrao)


def _get_files_ordenados(service, curso, sort: str, per_page: int = None):
    """Lista os arquivos do curso ordenados (order=desc).

    canvasapi 3.6.0: Course.get_files(**kwargs) empacota tudo em `_kwargs`, então
    um `per_page` do usuário nunca vira chave direta do PaginatedList e é trocado
    pelo default 100 (paginated_list.py:61). Quando per_page é pedido, montamos o
    PaginatedList na mão para que o per_page realmente chegue na query e force a
    paginação; sem per_page, usamos a chamada normal do canvasapi.
    """
    if not per_page:
        return curso.get_files(sort=sort, order="desc")

    from canvasapi.file import File
    from canvasapi.paginated_list import PaginatedList

    requester = service.canvas._Canvas__requester
    return PaginatedList(
        File, requester, "GET", f"courses/{curso.id}/files",
        per_page=per_page, sort=sort, order="desc",
    )


def _listar_com_pagina(paginado, contador: ContadorHTTP) -> list[tuple[int, object]]:
    """Itera um PaginatedList anotando de qual página (requisição) veio cada item."""
    inicio = contador.total
    saida = []
    for item in paginado:
        saida.append((contador.total - inicio, item))
    return saida


def _arquivo_para_dict(f, pastas: dict, modulos_por_arquivo: dict) -> dict:
    return {
        "id": f.id,
        "display_name": _atrib(f, "display_name"),
        "filename": _atrib(f, "filename"),
        "content_type": _atrib(f, "content-type"),
        "size": _atrib(f, "size"),
        "created_at": _atrib(f, "created_at"),
        "updated_at": _atrib(f, "updated_at"),
        "modified_at": _atrib(f, "modified_at"),
        "folder_id": _atrib(f, "folder_id"),
        "pasta": pastas.get(_atrib(f, "folder_id")),
        "modulos": modulos_por_arquivo.get(f.id, []),
        "locked": _atrib(f, "locked"),
        "hidden": _atrib(f, "hidden"),
    }


def coletar(curso_id: int, per_page: int = None, sort: str = "created_at") -> dict:
    service = CanvasService()
    contador = _instalar_contador(service)
    resultado: dict = {
        "curso_id": curso_id,
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "api": urlparse(service.api_url).netloc,
        "erros": {},
    }

    # 1. Usuário atual
    contador.etapa = "usuario"
    usuario = service.canvas.get_current_user()
    resultado["usuario_id"] = usuario.id

    # 2. Curso
    contador.etapa = "curso"
    curso = service.canvas.get_course(curso_id)
    resultado["curso_nome"] = _atrib(curso, "name")

    # 3. Pastas
    contador.etapa = "pastas"
    pastas: dict = {}
    try:
        for p in curso.get_folders():
            pastas[p.id] = _atrib(p, "full_name")
    except (Unauthorized, Forbidden) as e:
        resultado["erros"]["pastas"] = f"sem acesso às pastas ({e})"
    resultado["pastas"] = [{"id": k, "full_name": v} for k, v in pastas.items()]

    # 4. Módulos (com itens embutidos; cai para get_module_items se faltarem)
    contador.etapa = "modulos"
    modulos_por_arquivo: dict = {}
    modulos_info = []
    try:
        for m in curso.get_modules(include=["items"]):
            itens = _atrib(m, "items")
            origem = "include=items"
            if itens is None:
                itens = [vars(i) for i in m.get_module_items()]
                origem = "get_module_items"
            n_arquivos = 0
            for it in itens:
                if it.get("type") == "File" and it.get("content_id"):
                    modulos_por_arquivo.setdefault(it["content_id"], []).append(m.name)
                    n_arquivos += 1
            modulos_info.append({
                "id": m.id, "nome": m.name, "itens": len(itens),
                "arquivos": n_arquivos, "origem_itens": origem,
            })
    except (Unauthorized, Forbidden) as e:
        resultado["erros"]["modulos"] = f"sem acesso aos módulos ({e})"
    resultado["modulos"] = modulos_info

    # 5. Arquivos: listagem igual à do agente (sem parâmetros)
    contador.etapa = "arquivos_padrao"
    try:
        padrao = _listar_com_pagina(curso.get_files(), contador)
    except (Unauthorized, Forbidden) as e:
        resultado["erros"]["arquivos"] = (
            f"401/403: o curso {curso_id} não libera a listagem de arquivos para "
            f"este usuário (aba Arquivos oculta ou restrita). Detalhe: {e}"
        )
        padrao = []
    arquivos = [_arquivo_para_dict(f, pastas, modulos_por_arquivo) for _, f in padrao]
    resultado["arquivos"] = arquivos
    resultado["listagem_padrao"] = {
        "requisicoes": contador.por_etapa().get("arquivos_padrao", 0),
        "ordem_ids": [f["id"] for f in arquivos],
        "ordenada_por_nome": [a["display_name"].lower() for a in arquivos if a["display_name"]]
        == sorted(a["display_name"].lower() for a in arquivos if a["display_name"]),
    }

    # 6. Teste de ordenação: sort=<created_at|updated_at>, order=desc
    contador.etapa = "arquivos_ordenados"
    teste: dict = {"aceito": None, "sort": sort, "per_page": per_page}
    if "arquivos" not in resultado["erros"]:
        try:
            ordenados = _listar_com_pagina(
                _get_files_ordenados(service, curso, sort, per_page), contador
            )
            teste["aceito"] = True
            datas = [_atrib(f, sort) or "" for _, f in ordenados]
            ids_ordem = [f.id for _, f in ordenados]
            paginas = Counter(pag for pag, _ in ordenados)
            primeira = [f for pag, f in ordenados if pag == 1]
            n1 = len(primeira)
            mais_recentes = sorted(
                arquivos, key=lambda a: a[sort] or "", reverse=True
            )[:n1]
            teste.update({
                "requisicoes": contador.por_etapa().get("arquivos_ordenados", 0),
                "paginas": len(paginas),
                "itens_por_pagina": dict(sorted(paginas.items())),
                "itens_primeira_pagina": n1,
                "lista_toda_desc": datas == sorted(datas, reverse=True),
                "primeira_pagina_desc": datas[:n1] == sorted(datas[:n1], reverse=True),
                "primeira_pagina_sao_os_mais_recentes": (
                    {f.id for f in primeira} == {a["id"] for a in mais_recentes}
                ),
                "sem_repeticoes": len(ids_ordem) == len(set(ids_ordem)),
                "sem_faltantes": set(ids_ordem) == {a["id"] for a in arquivos},
                "ordem_ids": ids_ordem,
                "mesmo_conjunto_da_padrao": (
                    set(ids_ordem) == {a["id"] for a in arquivos}
                ),
            })
        except (Unauthorized, Forbidden) as e:
            teste.update({"aceito": None, "erro": f"sem acesso ({e})"})
        except Exception as e:  # 400 etc.: parâmetro recusado
            teste.update({"aceito": False, "erro": f"{type(e).__name__}: {e}"})
    resultado["teste_ordenacao"] = teste

    resultado["requisicoes"] = {
        "total": contador.total,
        "por_etapa": contador.por_etapa(),
        "detalhe": contador.registros,
    }
    return resultado


# ------------------------------------------------------------------------------
# Saída
# ------------------------------------------------------------------------------
def _tamanho(n) -> str:
    if n is None:
        return "-"
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unidade}" if unidade == "B" else f"{n:.1f}{unidade}"
        n /= 1024
    return f"{n:.1f}TB"


def _corta(texto, largura) -> str:
    texto = "-" if texto in (None, "") else str(texto)
    return texto if len(texto) <= largura else texto[: largura - 1] + "…"


def imprimir(r: dict) -> None:
    print(f"\nCurso {r['curso_id']}: {r.get('curso_nome')}  (API: {r['api']})")
    print(f"Usuário atual: id {r['usuario_id']}")

    print(f"\nPastas ({len(r['pastas'])}):")
    for p in r["pastas"]:
        print(f"  [{p['id']}] {p['full_name']}")

    print(f"\nMódulos ({len(r['modulos'])}):")
    for m in r["modulos"]:
        print(f"  [{m['id']}] {m['nome']}: {m['itens']} itens, {m['arquivos']} arquivo(s)"
              f" ({m['origem_itens']})")

    arquivos = r["arquivos"]
    print(f"\nArquivos ({len(arquivos)}), na ordem da listagem padrão do agente:")
    cab = (f"{'id':>9}  {'display_name':<42} {'content-type':<22} {'size':>8}  "
           f"{'created_at':<20} {'updated_at':<20} {'pasta':<28} módulo")
    print(cab)
    print("-" * len(cab))
    for a in arquivos:
        print(
            f"{a['id']:>9}  {_corta(a['display_name'], 42):<42} "
            f"{_corta(a['content_type'], 22):<22} {_tamanho(a['size']):>8}  "
            f"{_corta(a['created_at'], 20):<20} {_corta(a['updated_at'], 20):<20} "
            f"{_corta(a['pasta'], 28):<28} {_corta('; '.join(a['modulos']), 40)}"
        )

    lp = r["listagem_padrao"]
    print(f"\nListagem padrão (como o agente): {lp['requisicoes']} requisição(ões); "
          f"ordenada por nome: {lp['ordenada_por_nome']}")

    t = r["teste_ordenacao"]
    print(f"\nTeste sort={t.get('sort')}, order=desc, per_page={t.get('per_page')}:")
    for k, v in t.items():
        if k != "ordem_ids":
            print(f"  {k}: {v}")

    for etapa, msg in r["erros"].items():
        print(f"\n[AVISO] {etapa}: {msg}")

    req = r["requisicoes"]
    print(f"\nRequisições HTTP: {req['total']} no total")
    for etapa, n in req["por_etapa"].items():
        print(f"  {etapa}: {n}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--curso", type=int, required=True, help="id do curso no Canvas")
    parser.add_argument("--per-page", type=int, default=None,
                        help="itens por página na listagem de teste (get_files)")
    parser.add_argument("--sort", choices=["created_at", "updated_at"],
                        default="created_at",
                        help="campo de ordenação do teste (order=desc)")
    args = parser.parse_args()
    load_dotenv()

    try:
        r = coletar(args.curso, per_page=args.per_page, sort=args.sort)
    except CanvasAuthError as e:
        print(f"[ERRO] {e}")
        return 1
    except Unauthorized:
        print("[ERRO] 401: token inválido ou sem permissão para este recurso. "
              "Confira CANVAS_API_KEY no .env.")
        return 1
    except ResourceDoesNotExist:
        print(f"[ERRO] Curso {args.curso} não encontrado ou sem acesso para este usuário.")
        return 1

    imprimir(r)
    DIR_LOGS.mkdir(parents=True, exist_ok=True)
    saida = DIR_LOGS / f"diagnostico_{args.curso}.json"
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nDiagnóstico salvo em: {saida}")
    return 0 if not r["erros"] else 2


if __name__ == "__main__":
    sys.exit(main())
