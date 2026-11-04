"""Módulo RAG do Glaux: recuperação de trechos dos materiais das disciplinas.

Este módulo faz apenas a RECUPERAÇÃO de trechos relevantes. A montagem de
prompts e a geração de respostas com LLM ficam com os agentes.

Uso pelos agentes (executando a partir da raiz do repositório):

    from src.rag import buscar

    trechos = buscar("O que é overfitting?", course_id=123, k=5)
    for t in trechos:
        print(t["arquivo"], t["pagina"], t["score"], t["texto"])

Organização dos dados:
    data/raw/<course_id>/   PDFs de cada disciplina
    data/chroma/            índice vetorial persistido

Submódulos:
    extracao   leitura do texto dos PDFs, página a página
    chunking   divisão do texto em trechos
    indexacao  geração de embeddings e gravação no índice
    busca      consulta ao índice (interface pública: buscar)
"""

from .busca import buscar

__all__ = ["buscar"]
