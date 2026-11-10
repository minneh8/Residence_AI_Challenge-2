"""Dados e dublês de teste do gerador de questões.

Tudo aqui é fictício e escrito à mão: nada vem de data/raw, da rede ou do .env.
"""

import json

from src.agente_gerador.service import RespostaLLM

TRECHOS = [
    {
        "texto": "Overfitting ocorre quando o modelo memoriza o ruído do treino.",
        "arquivo": "aula_ficticia_01.pdf",
        "pagina": 3,
        "score": 0.91,
    },
    {
        "texto": "Na validação cruzada, os dados se dividem em k partes que alternam no teste.",
        "arquivo": "aula_ficticia_01.pdf",
        "pagina": 5,
        "score": 0.84,
    },
    {
        "texto": "A regularização L2 penaliza pesos grandes para reduzir a variância do modelo.",
        "arquivo": "aula_ficticia_02.pdf",
        "pagina": 2,
        "score": 0.77,
    },
    {
        "texto": "Apresentação do curso e critérios de avaliação.",
        "arquivo": "aula_ficticia_00.pdf",
        "pagina": 1,
        "score": 0.31,  # abaixo de SCORE_MINIMO: deve ser descartado
    },
]
TRECHO_FRACO = TRECHOS[3]


def referencia(trecho: dict) -> dict:
    """Referência no formato que o LLM devolve: só arquivo e página."""
    return {"arquivo": trecho["arquivo"], "pagina": trecho["pagina"]}


def questao_multipla(numero: int = 1, trecho: dict | None = None, **mudancas) -> dict:
    """Questão de múltipla escolha válida, como o LLM a devolveria."""
    dados = {
        "id": f"q{numero}",
        "tipo": "multipla_escolha",
        "enunciado": f"Pergunta de múltipla escolha número {numero}?",
        "alternativas": {letra: f"Alternativa {letra} da questão {numero}" for letra in "ABCD"},
        "correta": "B",
        "assunto": "overfitting",
        "trecho_referencia": referencia(trecho or TRECHOS[0]),
    }
    dados.update(mudancas)
    return dados


def questao_dissertativa(numero: int = 2, trecho: dict | None = None, **mudancas) -> dict:
    """Questão dissertativa válida, como o LLM a devolveria."""
    dados = {
        "id": f"q{numero}",
        "tipo": "dissertativa",
        "enunciado": f"Explique o conceito da questão {numero} com suas palavras.",
        "assunto": "validação cruzada",
        "trecho_referencia": referencia(trecho or TRECHOS[1]),
    }
    dados.update(mudancas)
    return dados


def resposta(*questoes: dict, finish_reason: str = "stop") -> RespostaLLM:
    """Resposta do LLM com estas questões, no JSON pedido pelo prompt."""
    conteudo = json.dumps({"questoes": list(questoes)}, ensure_ascii=False)
    return RespostaLLM(conteudo=conteudo, finish_reason=finish_reason)


class BuscarFalso:
    """RAG falso: devolve os trechos dados (até k) e anota cada chamada."""

    def __init__(self, trechos: list[dict]):
        self.trechos = [dict(t) for t in trechos]
        self.chamadas: list[dict] = []

    def __call__(self, pergunta: str, course_id: int, k: int = 5) -> list[dict]:
        self.chamadas.append({"pergunta": pergunta, "course_id": course_id, "k": k})
        return [dict(t) for t in self.trechos[:k]]


class LLMFalso:
    """LLM falso: devolve as respostas da fila, na ordem, e anota cada chamada.

    Um item da fila que seja uma exceção é lançado, como uma falha da API.
    """

    def __init__(self, *respostas: RespostaLLM | BaseException):
        self.fila = list(respostas)
        self.chamadas: list[list[dict]] = []

    def __call__(self, mensagens: list[dict]) -> RespostaLLM:
        self.chamadas.append(mensagens)
        if not self.fila:
            raise AssertionError("o LLM falso foi chamado mais vezes do que o teste previa")
        item = self.fila.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
