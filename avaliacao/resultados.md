# Avaliação do RAG

Esta pasta guarda o conjunto de perguntas usado para avaliar a recuperação de
trechos (`src.rag.buscar`) e os resultados de cada rodada.

## Formato de `perguntas.json`

Lista JSON de objetos, um por pergunta:

```json
[
  {
    "id": "p001",
    "course_id": 123,
    "pergunta": "O que é overfitting?",
    "esperado": [
      {"arquivo": "aula03.pdf", "pagina": 12}
    ]
  }
]
```

| Campo       | Tipo   | Descrição                                                        |
|-------------|--------|------------------------------------------------------------------|
| `id`        | string | Identificador único da pergunta.                                 |
| `course_id` | int    | Id da disciplina no Canvas (PDFs em `data/raw/<course_id>/`).    |
| `pergunta`  | string | Texto da pergunta, como um estudante faria.                      |
| `esperado`  | lista  | Trechos que deveriam ser recuperados: `arquivo` (str) e `pagina` (int). |

Uma busca é considerada acerto quando algum item retornado por `buscar` tem
o mesmo `arquivo` e `pagina` de um item de `esperado`.

## Resultados

Nenhuma rodada de avaliação ainda. A busca atual retorna dados simulados.
