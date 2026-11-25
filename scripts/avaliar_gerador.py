"""Avalia o Agente Gerador de Questões só com métricas automáticas.

Uso (a partir da raiz do projeto, a pasta que tem src/ e prompts/):
    python scripts/avaliar_gerador.py --curso N --dentro "<tema>" ... --fora "<tema>" ...
        [--quantidade 3] [--pausa 30] [--saida avaliacao/gerador_resultados.md]

Para cada tema, roda gerar_questoes() uma vez, com o RAG e o Groq de verdade, e
mede: status, se saiu ok na 1ª tentativa, retentativas e o motivo das falhas,
tempo, e a letra da correta antes e depois de embaralhar. Temas de dentro devem
sair "ok"; temas de fora, "sem_material".

Nada do conteúdo vai para a saída: nem texto dos PDFs, nem o texto das questões.
Entre um tema e outro espera --pausa segundos, por causa do limite de tokens por
minuto do plano gratuito do Groq.
"""

import argparse
import json
import logging
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

# Permite "from src..." e "from prompts..." ao rodar o script diretamente.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agente_gerador import service  # noqa: E402
from src.agente_gerador.models import LETRAS, QuestaoMultiplaEscolha  # noqa: E402


def motivo_da_falha(mensagem: str) -> str:
    """Resume em poucas palavras o aviso que gerar_questoes grava a cada tentativa falha."""
    if "Error code: 429" in mensagem:
        return "limite do Groq (429)"
    if "Error code: 400" in mensagem:
        return "JSON recusado pelo Groq (400)"
    if "vieram" in mensagem and "pedido era" in mensagem:
        return "quantidade errada"
    if "não foi recuperado" in mensagem:
        return "referência inventada"
    return "outra"


class _ColetorDeAvisos(logging.Handler):
    """Guarda os avisos do service (um por tentativa que falhou)."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.mensagens: list[str] = []

    def emit(self, record):
        self.mensagens.append(record.getMessage())


def letras_do_llm(conteudo: str | None) -> list[str]:
    """Letras de "correta" na resposta crua do LLM, ou seja, antes de embaralhar."""
    try:
        dados = json.loads(conteudo or "")
    except json.JSONDecodeError:
        return []
    return [
        q["correta"]
        for q in dados.get("questoes", [])
        if isinstance(q, dict) and q.get("tipo") == "multipla_escolha" and "correta" in q
    ]


def avaliar_tema(tema, grupo, curso, quantidade, buscar, chamar_llm, relogio) -> dict:
    """Roda uma geração e devolve as métricas dela (sem nenhum texto do conteúdo)."""
    respostas = []

    def chamar_e_guardar(mensagens):
        respostas.append(None)  # conta a chamada mesmo se ela lançar erro
        resposta = chamar_llm(mensagens)
        respostas[-1] = resposta
        return resposta

    coletor = _ColetorDeAvisos()
    nivel_antes = service.logger.level
    # Sem isto, o nível ERROR do logging.basicConfig de main() descartaria os avisos
    # antes de chegarem ao coletor.
    service.logger.setLevel(logging.WARNING)
    service.logger.addHandler(coletor)
    inicio = relogio()
    try:
        resultado = service.gerar_questoes(
            tema, curso, quantidade, buscar=buscar, chamar_llm=chamar_e_guardar
        )
    finally:
        service.logger.removeHandler(coletor)
        service.logger.setLevel(nivel_antes)
    tempo = relogio() - inicio

    antes, depois = [], []
    if resultado.status == "ok" and respostas and respostas[-1] is not None:
        antes = letras_do_llm(respostas[-1].conteudo)
        depois = [q.correta for q in resultado.questoes if isinstance(q, QuestaoMultiplaEscolha)]
    return {
        "grupo": grupo,
        "tema": tema,
        "status": resultado.status,
        "chamadas": len(respostas),
        "falhas": [motivo_da_falha(m) for m in coletor.mensagens],
        "tempo_s": round(tempo, 1),
        "corretas_antes": antes,
        "corretas_depois": depois,
    }


def resumir(linhas: list[dict]) -> dict:
    """Junta as métricas por grupo e no total."""
    dentro = [linha for linha in linhas if linha["grupo"] == "dentro"]
    fora = [linha for linha in linhas if linha["grupo"] == "fora"]
    ok = [linha for linha in linhas if linha["status"] == "ok"]
    tempos = [linha["tempo_s"] for linha in linhas]
    return {
        "dentro": Counter(linha["status"] for linha in dentro),
        "fora": Counter(linha["status"] for linha in fora),
        "total_dentro": len(dentro),
        "total_fora": len(fora),
        "ok_primeira": sum(1 for linha in ok if linha["chamadas"] == 1),
        "total_ok": len(ok),
        "retentativas": sum(max(linha["chamadas"] - 1, 0) for linha in linhas),
        "falhas": Counter(motivo for linha in linhas for motivo in linha["falhas"]),
        "tempo_medio": round(sum(tempos) / len(tempos), 1) if tempos else 0.0,
        "tempo_max": max(tempos, default=0.0),
        "antes": Counter(letra for linha in linhas for letra in linha["corretas_antes"]),
        "depois": Counter(letra for linha in linhas for letra in linha["corretas_depois"]),
    }


def _contagem(contador: Counter, chaves) -> str:
    return " · ".join(f"{chave} {contador.get(chave, 0)}" for chave in chaves)


def relatorio(linhas: list[dict], resumo: dict, curso: int, quantidade: int, hoje: str) -> str:
    """Texto em Markdown com a tabela por tema e o resumo."""
    status = ("ok", "sem_material", "erro")
    saida = [
        "# Avaliação do Agente Gerador de Questões",
        "",
        f"Gerado por `scripts/avaliar_gerador.py` em {hoje}. Curso {curso}, {quantidade} "
        f"questões por tema, uma geração por tema. Modelo `{service.MODELO}`, "
        f"`K_MINIMO={service.K_MINIMO}`, `SCORE_MINIMO={service.SCORE_MINIMO}`.",
        "Só métricas automáticas: nenhum texto dos PDFs nem das questões.",
        "",
        "| grupo | tema | status | chamadas | falhas | tempo (s) | correta antes → depois |",
        "|---|---|---|---|---|---|---|",
    ]
    for linha in linhas:
        falhas = ", ".join(linha["falhas"]) or "—"
        letras = (
            f"{''.join(linha['corretas_antes'])} → {''.join(linha['corretas_depois'])}"
            if linha["corretas_antes"] or linha["corretas_depois"]
            else "—"
        )
        saida.append(
            f"| {linha['grupo']} | {linha['tema']} | {linha['status']} | {linha['chamadas']} "
            f"| {falhas} | {linha['tempo_s']} | {letras} |"
        )
    falhas = ", ".join(f"{motivo} {n}" for motivo, n in resumo["falhas"].most_common()) or "nenhuma"
    saida += [
        "",
        "## Resumo",
        "",
        f"- Temas de dentro ({resumo['total_dentro']}): {_contagem(resumo['dentro'], status)}",
        f"- Temas de fora ({resumo['total_fora']}): {_contagem(resumo['fora'], status)} "
        "(o esperado é tudo em sem_material)",
        f"- ok na 1ª tentativa: {resumo['ok_primeira']} de {resumo['total_ok']}",
        f"- Retentativas: {resumo['retentativas']} (motivos: {falhas})",
        f"- Tempo por geração: média {resumo['tempo_medio']} s, máximo {resumo['tempo_max']} s",
        f"- Letra correta antes de embaralhar: {_contagem(resumo['antes'], LETRAS)}",
        f"- Letra correta depois de embaralhar: {_contagem(resumo['depois'], LETRAS)}",
    ]
    return "\n".join(saida) + "\n"


def main(argv=None, buscar=None, chamar_llm=None, dormir=time.sleep, relogio=time.perf_counter):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--curso", type=int, required=True, help="id da disciplina no Canvas")
    parser.add_argument("--dentro", nargs="+", default=[], help="temas que a disciplina cobre")
    parser.add_argument("--fora", nargs="+", default=[], help="temas que a disciplina não cobre")
    parser.add_argument("--quantidade", type=int, default=3, help="questões por tema (padrão: 3)")
    parser.add_argument("--pausa", type=float, default=30.0, help="segundos entre temas")
    parser.add_argument("--saida", type=Path, help="arquivo .md para gravar o relatório")
    args = parser.parse_args(argv)
    if not args.dentro and not args.fora:
        parser.error("informe pelo menos um tema em --dentro ou --fora.")
    if not 1 <= args.quantidade <= service.TETO_QUESTOES:
        parser.error(f"--quantidade deve ser um número de 1 a {service.TETO_QUESTOES}.")

    logging.basicConfig(level=logging.ERROR)  # os avisos do service vão para a tabela
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if buscar is None:
        from src.rag import buscar  # importa o RAG (e o modelo E5) só quando vai usar

    temas = [("dentro", t) for t in args.dentro] + [("fora", t) for t in args.fora]
    linhas = []
    for numero, (grupo, tema) in enumerate(temas, start=1):
        if numero > 1:
            dormir(args.pausa)
        linha = avaliar_tema(
            tema, grupo, args.curso, args.quantidade, buscar,
            chamar_llm or service.chamar_groq, relogio,
        )
        linhas.append(linha)
        print(
            f"[{numero}/{len(temas)}] {grupo} | {tema}: {linha['status']} "
            f"({linha['chamadas']} chamada(s), {linha['tempo_s']} s)",
            file=sys.stderr,
        )

    hoje = date.today().isoformat()
    texto = relatorio(linhas, resumir(linhas), args.curso, args.quantidade, hoje)
    print(texto, end="")
    if args.saida:
        args.saida.parent.mkdir(parents=True, exist_ok=True)
        args.saida.write_text(texto, encoding="utf-8")
        print(f"Relatório salvo em {args.saida}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
