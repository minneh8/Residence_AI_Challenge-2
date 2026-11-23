"""Aplica o classificador a todos os PDFs de data/logs/diagnostico_<curso>.json.

Somente leitura: lê os logs gerados por scripts/diagnostico_canvas.py e imprime
uma tabela Markdown (arquivo | curso | categoria | origem), com os indefinidos
em negrito e listados no fim. Páginas = None (o diagnóstico não conta páginas).

Uso (na raiz do repo):
    .venv\\Scripts\\python.exe scripts\\classificar_logs.py 93527 93511 93532
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from src.agente_canvas.classificador import classificar  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
print("| arquivo | curso | categoria | origem |\n|---|---|---|---|")
indef = []
for curso in sys.argv[1:]:
    r = json.loads(Path(f"data/logs/diagnostico_{curso}.json").read_text(encoding="utf-8"))
    for a in r.get("arquivos", []):
        nome = a.get("display_name") or ""
        if not nome.lower().endswith(".pdf"):
            continue
        mods = a.get("modulos") or []
        mod = mods[0] if mods else None
        if isinstance(mod, dict):
            mod = mod.get("nome")
        cat, org = classificar(nome, mod, a.get("pasta"), a.get("size"), None)
        marca = "**" if cat == "indefinido" else ""
        print(f"| {marca}{nome}{marca} | {curso} | {marca}{cat}{marca} | {org} |")
        if cat == "indefinido":
            indef.append((curso, nome))
print(f"\nIndefinidos ({len(indef)}):")
for c, n in indef:
    print(f"- {c}: {n}")
