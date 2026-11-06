"""Busca de trechos relevantes para uma pergunta.

Interface pública consumida pelos agentes:

    buscar(pergunta: str, course_id: int, k: int = 5) -> list[dict]

Cada item retornado tem as chaves:
    texto   (str)   conteúdo do trecho
    arquivo (str)   nome do PDF de origem
    pagina  (int)   página do PDF (começando em 1)
    score   (float) relevância; maior = mais relevante

Os itens vêm ordenados por score decrescente, com no máximo k elementos.

ATENÇÃO: nesta etapa a função retorna DADOS SIMULADOS (mock), apenas para que
os agentes possam testar a integração. Não há índice, embeddings nem leitura
de PDFs ainda.
"""

# --- DADOS SIMULADOS (MOCK) ---------------------------------------------------
# Remover quando a busca real no índice (data/chroma/) for implementada.
_TRECHOS_SIMULADOS: list[dict] = [
    {
        "texto": "[SIMULADO] Trecho de exemplo 1 retornado pelo RAG.",
        "arquivo": "exemplo_simulado_aula01.pdf",
        "pagina": 1,
        "score": 0.95,
    },
    {
        "texto": "[SIMULADO] Trecho de exemplo 2 retornado pelo RAG.",
        "arquivo": "exemplo_simulado_aula01.pdf",
        "pagina": 3,
        "score": 0.87,
    },
    {
        "texto": "[SIMULADO] Trecho de exemplo 3 retornado pelo RAG.",
        "arquivo": "exemplo_simulado_aula02.pdf",
        "pagina": 2,
        "score": 0.80,
    },
    {
        "texto": "[SIMULADO] Trecho de exemplo 4 retornado pelo RAG.",
        "arquivo": "exemplo_simulado_aula02.pdf",
        "pagina": 5,
        "score": 0.72,
    },
    {
        "texto": "[SIMULADO] Trecho de exemplo 5 retornado pelo RAG.",
        "arquivo": "exemplo_simulado_aula03.pdf",
        "pagina": 4,
        "score": 0.65,
    },
]
# ------------------------------------------------------------------------------


def buscar(pergunta: str, course_id: int, k: int = 5) -> list[dict]:
    """Retorna os k trechos mais relevantes para a pergunta na disciplina.

    Args:
        pergunta: texto da pergunta do estudante. Não pode ser vazio.
        course_id: id da disciplina no Canvas.
        k: quantidade máxima de trechos retornados. Deve ser maior que zero.

    Returns:
        Lista de dicts com as chaves texto, arquivo, pagina e score,
        ordenada por score decrescente.

    Raises:
        ValueError: se a pergunta for vazia (ou só espaços) ou se k <= 0.

    ATENÇÃO: implementação SIMULADA. Ignora pergunta e course_id e devolve
    trechos fixos marcados com "[SIMULADO]".
    """
    if not isinstance(pergunta, str) or not pergunta.strip():
        raise ValueError("A pergunta não pode ser vazia.")
    if k <= 0:
        raise ValueError("k deve ser maior que zero.")

    # MOCK: substituir pela consulta ao índice vetorial do course_id.
    return [dict(trecho) for trecho in _TRECHOS_SIMULADOS[:k]]
