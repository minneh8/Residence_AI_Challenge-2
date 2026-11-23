"""Testa a classificação (regras + fallback de LLM) de UM arquivo real do Canvas.

Uso (a partir da raiz do repositório):
    python scripts/testar_classificador_llm.py --curso 93511 --arquivo "Material de Apoio GP - ENG_SOFT.pdf"
    (acrescente --forcar-llm para chamar a LLM mesmo quando as regras decidem)

Baixa só esse arquivo para uma pasta temporária (fora de data/raw), conta as
páginas, roda classificar() e, se der "indefinido", classificar_llm(). Mostra
categoria, origem, confiança, justificativa e o tempo e os tokens da chamada à
LLM. Não grava nada no catálogo nem no estado do aluno; a pasta temporária é
apagada no fim.
"""

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

from src.agente_canvas import classificador_llm  # noqa: E402
from src.agente_canvas.classificador import classificar  # noqa: E402
from src.agente_canvas.service import CanvasService, _contar_paginas_pdf  # noqa: E402


class LLMMedida:
    """Envolve o cliente da Groq para medir o tempo e guardar a resposta."""

    def __init__(self, cliente):
        self.cliente = cliente
        self.tempo_s = None
        self.resposta = None

    def invoke(self, mensagens):
        inicio = time.perf_counter()
        try:
            self.resposta = self.cliente.invoke(mensagens)
            return self.resposta
        finally:
            self.tempo_s = time.perf_counter() - inicio


def _tokens(resposta) -> str:
    uso = getattr(resposta, "usage_metadata", None) or {}
    if uso:
        return (f"{uso.get('input_tokens')} de entrada + {uso.get('output_tokens')} "
                f"de saída = {uso.get('total_tokens')}")
    meta = (getattr(resposta, "response_metadata", None) or {}).get("token_usage") or {}
    if meta:
        return (f"{meta.get('prompt_tokens')} de entrada + {meta.get('completion_tokens')} "
                f"de saída = {meta.get('total_tokens')}")
    return "não informado"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--curso", type=int, required=True, help="id do curso no Canvas")
    parser.add_argument("--arquivo", required=True, help="nome do arquivo no Canvas (display_name)")
    parser.add_argument("--forcar-llm", action="store_true",
                        help="chama a LLM mesmo quando as regras decidem (só para teste)")
    args = parser.parse_args()

    load_dotenv()
    service = CanvasService()
    service.validar_token()
    curso = service._com_retentativas(
        lambda: service.canvas.get_course(args.curso), f"abrir o curso {args.curso}")

    alvo = args.arquivo.strip().lower()
    arquivo = next(
        (a for a in service._iterar_paginado(lambda: curso.get_files(), "listar os arquivos")
         if (getattr(a, "display_name", "") or "").strip().lower() == alvo),
        None,
    )
    if arquivo is None:
        print(f"Arquivo '{args.arquivo}' não encontrado no curso {args.curso}.")
        return 1

    modulo = service._mapear_modulos_arquivos(curso).get(int(arquivo.id))
    pasta_tmp = Path(tempfile.mkdtemp(prefix="glaux_llm_"))
    try:
        caminho = pasta_tmp / f"{arquivo.id}.pdf"
        service._com_retentativas(lambda: arquivo.download(str(caminho)), "baixar o arquivo")
        paginas = _contar_paginas_pdf(caminho)
        tamanho = getattr(arquivo, "size", None) or caminho.stat().st_size

        print(f"Arquivo:  {arquivo.display_name} (id {arquivo.id})")
        print(f"Módulo:   {modulo or '(sem módulo)'}")
        print(f"Tamanho:  {tamanho / 1024 / 1024:.1f} MB | Páginas: {paginas}")
        print(f"Pasta temporária: {pasta_tmp}")

        categoria, origem = classificar(arquivo.display_name, modulo, None, tamanho, paginas)
        print(f"\nRegras:   categoria={categoria} | origem={origem}")
        if categoria != "indefinido" and not args.forcar_llm:
            print("As regras decidiram; a LLM não foi chamada (use --forcar-llm para testá-la).")
            return 0
        if categoria != "indefinido":
            print("--forcar-llm: chamando a LLM mesmo assim (no agente ela não seria chamada).")

        llm = LLMMedida(classificador_llm._criar_llm())
        texto = classificador_llm.texto_inicial(caminho)
        print(f"\nTexto enviado à LLM: {len(texto)} caracteres das "
              f"{classificador_llm.PAGINAS_LIDAS} primeiras páginas.")
        r = classificador_llm.classificar_llm(
            caminho, arquivo.display_name, modulo, paginas, llm=llm)

        print("\nLLM:")
        print(f"  categoria:     {r['categoria']}")
        print(f"  origem:        {r['origem']}")
        print(f"  confiança:     {r['confianca']}")
        print(f"  justificativa: {r['justificativa']}")
        if llm.tempo_s is not None:
            print(f"  tempo:         {llm.tempo_s:.2f} s")
        if llm.resposta is not None:
            print(f"  tokens:        {_tokens(llm.resposta)}")
            print(f"  modelo:        {classificador_llm.MODELO_PADRAO}")
        print("\nNada foi gravado no catálogo nem no estado do aluno.")
        return 0
    finally:
        shutil.rmtree(pasta_tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
