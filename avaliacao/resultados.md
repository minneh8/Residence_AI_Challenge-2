# Avaliação do RAG

Esta pasta guarda o conjunto de perguntas usado para avaliar a recuperação de
trechos (`src.rag.busca.buscar_na_colecao`) e os resultados de cada rodada.

## Formato de `perguntas.json`

Lista JSON de objetos, um por pergunta:

```json
[
  {
    "id": "q03",
    "pergunta": "O que é o método hipotético-dedutivo?",
    "course_id": 93527,
    "tipo": "direta",
    "origem": "relatorio-extracao",
    "respostas": [
      {"arquivo": "aula01.pdf", "paginas": [23]}
    ],
    "status": "confirmada"
  }
]
```

| Campo       | Tipo   | Descrição                                                                 |
|-------------|--------|---------------------------------------------------------------------------|
| `id`        | string | Identificador único da pergunta.                                          |
| `pergunta`  | string | Texto da pergunta, como um estudante faria.                               |
| `course_id` | int    | Id da disciplina no Canvas (PDFs em `data/raw/<course_id>/`).             |
| `tipo`      | string | `direta`, `termo`, `parafrase`, `varias` ou `fora` (fora do conteúdo).    |
| `origem`    | string | De onde a pergunta veio (ex.: `lista1-q1`, `material`, `manual`).         |
| `respostas` | lista  | Respostas aceitas: `arquivo` (str) e `paginas` (lista de int, a partir de 1). Vazia para `fora`. |
| `status`    | string | `confirmada` (revisada) ou `sugerida` (ainda não revisada).               |

Uma busca é considerada acerto quando algum resultado tem o mesmo `arquivo`
de uma resposta aceita e cobre alguma das `paginas` dela, ou seja,
`pagina <= p <= pagina_fim`.

## Como rodar a avaliação

Com o curso indexado nas coleções `rag_j1_s0` e `rag_j3_s1`
(`scripts/indexar.py <course_id> 1 0` e `scripts/indexar.py <course_id> 3 1`):

```
python scripts/avaliar.py                      # só perguntas "confirmada"
python scripts/avaliar.py --incluir-sugeridas  # também as "sugerida" (prévia)
```

Para cada coleção e para k = 3 e 5, o script calcula, nas perguntas com
resposta, Recall@k, MRR e a média de páginas cobertas por resultado, no total
e por `tipo`. Para as perguntas `fora`, compara o maior score de cada uma com
o mínimo, a média e o máximo do maior score das perguntas com resposta. Também
lista as perguntas que erraram, com o primeiro resultado e seu score.

Cada execução acrescenta uma seção "Rodada" ao final deste arquivo, sem
trechos dos PDFs. Com menos de 5 perguntas usadas, o resultado é marcado como
não conclusivo.

## Resultados

### Rodada 2026-11-10 13:52

- Coleções: rag_j1_s0, rag_j3_s1
- k: 3, 5
- Perguntas usadas: 23 (20 com resposta, 3 do tipo "fora")
- Sugeridas incluídas: sim
- Acerto: mesmo arquivo de uma resposta aceita e pagina <= p <= pagina_fim para alguma página esperada.
- **Prévia:** inclui perguntas ainda não confirmadas.

#### Perguntas com resposta

| Métrica | rag_j1_s0 k=3 | rag_j1_s0 k=5 | rag_j3_s1 k=3 | rag_j3_s1 k=5 |
|---|---|---|---|---|
| **Total** (n=20) Recall@k | 0.750 | 0.750 | 0.700 | 0.700 |
| Total MRR | 0.617 | 0.617 | 0.592 | 0.592 |
| Total páginas/resultado | 1.00 | 1.00 | 3.62 | 3.53 |
| **tipo direta** (n=4) Recall@k | 1.000 | 1.000 | 1.000 | 1.000 |
| tipo direta MRR | 0.875 | 0.875 | 0.875 | 0.875 |
| tipo direta páginas/resultado | 1.00 | 1.00 | 3.83 | 3.90 |
| **tipo parafrase** (n=8) Recall@k | 0.625 | 0.625 | 0.500 | 0.500 |
| tipo parafrase MRR | 0.438 | 0.438 | 0.375 | 0.375 |
| tipo parafrase páginas/resultado | 1.00 | 1.00 | 3.29 | 3.23 |
| **tipo termo** (n=5) Recall@k | 0.800 | 0.800 | 0.800 | 0.800 |
| tipo termo MRR | 0.667 | 0.667 | 0.667 | 0.667 |
| tipo termo páginas/resultado | 1.00 | 1.00 | 4.13 | 3.64 |
| **tipo varias** (n=3) Recall@k | 0.667 | 0.667 | 0.667 | 0.667 |
| tipo varias MRR | 0.667 | 0.667 | 0.667 | 0.667 |
| tipo varias páginas/resultado | 1.00 | 1.00 | 3.33 | 3.67 |

#### Maior score: "fora" × com resposta (top-1, k=5)

| Pergunta | rag_j1_s0 | rag_j3_s1 |
|---|---|---|
| q24 fora: Como cozinhar arroz? | 0.7923 | 0.7820 |
| q25 fora: Quem ganhou a Copa do Mundo de 2022? | 0.7649 | 0.7637 |
| q26 fora: Como fazer deploy de uma aplicação no Kubernetes? | 0.8054 | 0.8106 |
| com resposta (mín) | 0.8325 | 0.8175 |
| com resposta (média) | 0.8546 | 0.8457 |
| com resposta (máx) | 0.8876 | 0.8762 |

#### Perguntas que erraram

- **rag_j1_s0 k=3** (5 erro(s))
  - q10 [termo] O que são ameaças à validade de um estudo? → 1º: aula02.pdf p.26 (score 0.8652)
  - q12 [varias] Como planejar um experimento para comparar o tempo de resposta de duas bibliotecas? → 1º: aula02.pdf p.43 (score 0.8592)
  - q16 [parafrase] Se cada engenheiro roda os testes em um turno e em uma máquina diferentes, como saber se o resultado veio do compilador? → 1º: aula02.pdf p.31 (score 0.8396)
  - q17 [parafrase] Qual medida representa melhor o valor típico quando há valores muito altos? → 1º: aula04.pdf p.42 (score 0.8325)
  - q28 [parafrase] Quando é melhor fazer um estudo de caso em vez de um experimento? → 1º: aula03.pdf p.3 (score 0.8414)
- **rag_j1_s0 k=5** (5 erro(s))
  - q10 [termo] O que são ameaças à validade de um estudo? → 1º: aula02.pdf p.26 (score 0.8652)
  - q12 [varias] Como planejar um experimento para comparar o tempo de resposta de duas bibliotecas? → 1º: aula02.pdf p.43 (score 0.8592)
  - q16 [parafrase] Se cada engenheiro roda os testes em um turno e em uma máquina diferentes, como saber se o resultado veio do compilador? → 1º: aula02.pdf p.31 (score 0.8396)
  - q17 [parafrase] Qual medida representa melhor o valor típico quando há valores muito altos? → 1º: aula04.pdf p.42 (score 0.8325)
  - q28 [parafrase] Quando é melhor fazer um estudo de caso em vez de um experimento? → 1º: aula03.pdf p.3 (score 0.8414)
- **rag_j3_s1 k=3** (6 erro(s))
  - q12 [varias] Como planejar um experimento para comparar o tempo de resposta de duas bibliotecas? → 1º: aula02.pdf p.42-43 (score 0.8679)
  - q14 [parafrase] Como evitar que outros fatores interfiram no resultado de um experimento? → 1º: aula01.pdf p.35-37 (score 0.8415)
  - q16 [parafrase] Se cada engenheiro roda os testes em um turno e em uma máquina diferentes, como saber se o resultado veio do compilador? → 1º: aula00.pdf p.4-6 (score 0.8403)
  - q27 [termo] O que é validade de construto? → 1º: aula02.pdf p.11-13 (score 0.8421)
  - q28 [parafrase] Quando é melhor fazer um estudo de caso em vez de um experimento? → 1º: aula02.pdf p.42-43 (score 0.8437)
  - q32 [parafrase] O que meu trabalho precisa ter para ser bem avaliado? → 1º: aula02.pdf p.7-9 (score 0.8338)
- **rag_j3_s1 k=5** (6 erro(s))
  - q12 [varias] Como planejar um experimento para comparar o tempo de resposta de duas bibliotecas? → 1º: aula02.pdf p.42-43 (score 0.8679)
  - q14 [parafrase] Como evitar que outros fatores interfiram no resultado de um experimento? → 1º: aula01.pdf p.35-37 (score 0.8415)
  - q16 [parafrase] Se cada engenheiro roda os testes em um turno e em uma máquina diferentes, como saber se o resultado veio do compilador? → 1º: aula00.pdf p.4-6 (score 0.8403)
  - q27 [termo] O que é validade de construto? → 1º: aula02.pdf p.11-13 (score 0.8421)
  - q28 [parafrase] Quando é melhor fazer um estudo de caso em vez de um experimento? → 1º: aula02.pdf p.42-43 (score 0.8437)
  - q32 [parafrase] O que meu trabalho precisa ter para ser bem avaliado? → 1º: aula02.pdf p.7-9 (score 0.8338)

### Rodada 2026-11-10 14:14

- Coleções: rag_j1_s0, rag_j3_s1
- k: 3, 5
- Perguntas usadas: 22 (19 com resposta, 3 do tipo "fora")
- Sugeridas incluídas: sim
- Acerto: mesmo arquivo de uma resposta aceita e pagina <= p <= pagina_fim para alguma página esperada.
- **Prévia:** inclui perguntas ainda não confirmadas.

#### Perguntas com resposta

| Métrica | rag_j1_s0 k=3 | rag_j1_s0 k=5 | rag_j3_s1 k=3 | rag_j3_s1 k=5 |
|---|---|---|---|---|
| **Total** (n=19) Recall@k | 0.789 | 0.842 | 0.632 | 0.842 |
| Total MRR | 0.640 | 0.651 | 0.553 | 0.600 |
| Total páginas/resultado | 1.00 | 1.00 | 3.60 | 3.67 |
| **tipo direta** (n=4) Recall@k | 1.000 | 1.000 | 0.750 | 1.000 |
| tipo direta MRR | 0.875 | 0.875 | 0.625 | 0.688 |
| tipo direta páginas/resultado | 1.00 | 1.00 | 3.83 | 3.70 |
| **tipo parafrase** (n=7) Recall@k | 0.714 | 0.857 | 0.429 | 0.714 |
| tipo parafrase MRR | 0.476 | 0.505 | 0.357 | 0.421 |
| tipo parafrase páginas/resultado | 1.00 | 1.00 | 3.33 | 3.46 |
| **tipo termo** (n=5) Recall@k | 0.800 | 0.800 | 0.800 | 0.800 |
| tipo termo MRR | 0.667 | 0.667 | 0.700 | 0.700 |
| tipo termo páginas/resultado | 1.00 | 1.00 | 3.80 | 3.80 |
| **tipo varias** (n=3) Recall@k | 0.667 | 0.667 | 0.667 | 1.000 |
| tipo varias MRR | 0.667 | 0.667 | 0.667 | 0.733 |
| tipo varias páginas/resultado | 1.00 | 1.00 | 3.56 | 3.93 |

#### Maior score: "fora" × com resposta (top-1, k=5)

| Pergunta | rag_j1_s0 | rag_j3_s1 |
|---|---|---|
| q24 fora: Como cozinhar arroz? | 0.7923 | 0.7891 |
| q25 fora: Quem ganhou a Copa do Mundo de 2022? | 0.7649 | 0.7541 |
| q26 fora: Como fazer deploy de uma aplicação no Kubernetes? | 0.8054 | 0.8129 |
| com resposta (mín) | 0.8283 | 0.8154 |
| com resposta (média) | 0.8548 | 0.8445 |
| com resposta (máx) | 0.8876 | 0.8762 |

#### Perguntas que erraram

- **rag_j1_s0 k=3** (4 erro(s))
  - q10 [termo] O que são ameaças à validade de um estudo? → 1º: aula02.pdf p.26 (score 0.8652)
  - q12 [varias] Como planejar um experimento para comparar o tempo de resposta de duas bibliotecas? → 1º: aula04.pdf p.26 (score 0.8534)
  - q16 [parafrase] Se cada engenheiro roda os testes em um turno e em uma máquina diferentes, como saber se o resultado veio do compilador? → 1º: aula02.pdf p.31 (score 0.8396)
  - q17 [parafrase] Qual medida representa melhor o valor típico quando há valores muito altos? → 1º: aula04.pdf p.13 (score 0.8283)
- **rag_j1_s0 k=5** (3 erro(s))
  - q10 [termo] O que são ameaças à validade de um estudo? → 1º: aula02.pdf p.26 (score 0.8652)
  - q12 [varias] Como planejar um experimento para comparar o tempo de resposta de duas bibliotecas? → 1º: aula04.pdf p.26 (score 0.8534)
  - q16 [parafrase] Se cada engenheiro roda os testes em um turno e em uma máquina diferentes, como saber se o resultado veio do compilador? → 1º: aula02.pdf p.31 (score 0.8396)
- **rag_j3_s1 k=3** (7 erro(s))
  - q12 [varias] Como planejar um experimento para comparar o tempo de resposta de duas bibliotecas? → 1º: aula00.pdf p.15-17 (score 0.8505)
  - q14 [parafrase] Como evitar que outros fatores interfiram no resultado de um experimento? → 1º: aula01.pdf p.35-37 (score 0.8415)
  - q15 [direta] Para que serve a aleatorização em um experimento? → 1º: aula03.pdf p.13-16 (score 0.8154)
  - q16 [parafrase] Se cada engenheiro roda os testes em um turno e em uma máquina diferentes, como saber se o resultado veio do compilador? → 1º: aula03.pdf p.13-16 (score 0.8387)
  - q27 [termo] O que é validade de construto? → 1º: aula02.pdf p.11-13 (score 0.8421)
  - q31 [parafrase] Se não achei nenhuma prova de que algo existe, posso concluir que não existe? → 1º: aula01.pdf p.35-37 (score 0.8360)
  - q32 [parafrase] O que meu trabalho precisa ter para ser bem avaliado? → 1º: aula02.pdf p.7-9 (score 0.8338)
- **rag_j3_s1 k=5** (3 erro(s))
  - q16 [parafrase] Se cada engenheiro roda os testes em um turno e em uma máquina diferentes, como saber se o resultado veio do compilador? → 1º: aula03.pdf p.13-16 (score 0.8387)
  - q27 [termo] O que é validade de construto? → 1º: aula02.pdf p.11-13 (score 0.8421)
  - q32 [parafrase] O que meu trabalho precisa ter para ser bem avaliado? → 1º: aula02.pdf p.7-9 (score 0.8338)

### Rodada 2026-11-10 15:06

- Coleções: rag_j1_s0, rag_j3_s1
- k: 3, 5
- Perguntas usadas: 21 (18 com resposta, 3 do tipo "fora")
- Sugeridas incluídas: sim
- Acerto: mesmo arquivo de uma resposta aceita e pagina <= p <= pagina_fim para alguma página esperada.
- **Prévia:** inclui perguntas ainda não confirmadas.

#### Perguntas com resposta

| Métrica | rag_j1_s0 k=3 | rag_j1_s0 k=5 | rag_j3_s1 k=3 | rag_j3_s1 k=5 |
|---|---|---|---|---|
| **Total** (n=18) Recall@k | 0.778 | 0.778 | 0.667 | 0.778 |
| Total MRR | 0.657 | 0.657 | 0.583 | 0.611 |
| Total páginas/resultado | 1.00 | 1.00 | 3.61 | 3.60 |
| **tipo direta** (n=3) Recall@k | 1.000 | 1.000 | 1.000 | 1.000 |
| tipo direta MRR | 1.000 | 1.000 | 0.833 | 0.833 |
| tipo direta páginas/resultado | 1.00 | 1.00 | 3.67 | 3.53 |
| **tipo parafrase** (n=7) Recall@k | 0.714 | 0.714 | 0.429 | 0.571 |
| tipo parafrase MRR | 0.500 | 0.500 | 0.357 | 0.393 |
| tipo parafrase páginas/resultado | 1.00 | 1.00 | 3.29 | 3.31 |
| **tipo termo** (n=5) Recall@k | 0.800 | 0.800 | 0.800 | 0.800 |
| tipo termo MRR | 0.667 | 0.667 | 0.700 | 0.700 |
| tipo termo páginas/resultado | 1.00 | 1.00 | 3.80 | 3.80 |
| **tipo varias** (n=3) Recall@k | 0.667 | 0.667 | 0.667 | 1.000 |
| tipo varias MRR | 0.667 | 0.667 | 0.667 | 0.750 |
| tipo varias páginas/resultado | 1.00 | 1.00 | 4.00 | 4.00 |

#### Maior score: "fora" × com resposta (top-1, k=5)

| Pergunta | rag_j1_s0 | rag_j3_s1 |
|---|---|---|
| q24 fora: Como cozinhar arroz? | 0.7923 | 0.7785 |
| q25 fora: Quem ganhou a Copa do Mundo de 2022? | 0.7649 | 0.7541 |
| q26 fora: Como fazer deploy de uma aplicação no Kubernetes? | 0.8054 | 0.8129 |
| com resposta (mín) | 0.8325 | 0.8320 |
| com resposta (média) | 0.8558 | 0.8458 |
| com resposta (máx) | 0.8876 | 0.8762 |

#### Perguntas que erraram

- **rag_j1_s0 k=3** (4 erro(s))
  - q10 [termo] O que são ameaças à validade de um estudo? → 1º: aula02.pdf p.26 (score 0.8652)
  - q12 [varias] Como planejar um experimento para comparar o tempo de resposta de duas bibliotecas? → 1º: aula04.pdf p.26 (score 0.8534)
  - q16 [parafrase] Se cada engenheiro roda os testes em um turno e em uma máquina diferentes, como saber se o resultado veio do compilador? → 1º: aula02.pdf p.31 (score 0.8396)
  - q17 [parafrase] Qual medida representa melhor o valor típico quando há valores muito altos? → 1º: aula04.pdf p.42 (score 0.8325)
- **rag_j1_s0 k=5** (4 erro(s))
  - q10 [termo] O que são ameaças à validade de um estudo? → 1º: aula02.pdf p.26 (score 0.8652)
  - q12 [varias] Como planejar um experimento para comparar o tempo de resposta de duas bibliotecas? → 1º: aula04.pdf p.26 (score 0.8534)
  - q16 [parafrase] Se cada engenheiro roda os testes em um turno e em uma máquina diferentes, como saber se o resultado veio do compilador? → 1º: aula02.pdf p.31 (score 0.8396)
  - q17 [parafrase] Qual medida representa melhor o valor típico quando há valores muito altos? → 1º: aula04.pdf p.42 (score 0.8325)
- **rag_j3_s1 k=3** (6 erro(s))
  - q12 [varias] Como planejar um experimento para comparar o tempo de resposta de duas bibliotecas? → 1º: aula04.pdf p.27-31 (score 0.8449)
  - q14 [parafrase] Como evitar que outros fatores interfiram no resultado de um experimento? → 1º: aula01.pdf p.35-37 (score 0.8415)
  - q16 [parafrase] Se cada engenheiro roda os testes em um turno e em uma máquina diferentes, como saber se o resultado veio do compilador? → 1º: aula03.pdf p.13-16 (score 0.8387)
  - q27 [termo] O que é validade de construto? → 1º: aula02.pdf p.11-13 (score 0.8421)
  - q31 [parafrase] Se não achei nenhuma prova de que algo existe, posso concluir que não existe? → 1º: aula01.pdf p.35-37 (score 0.8360)
  - q32 [parafrase] O que meu trabalho precisa ter para ser bem avaliado? → 1º: aula02.pdf p.7-9 (score 0.8338)
- **rag_j3_s1 k=5** (4 erro(s))
  - q14 [parafrase] Como evitar que outros fatores interfiram no resultado de um experimento? → 1º: aula01.pdf p.35-37 (score 0.8415)
  - q16 [parafrase] Se cada engenheiro roda os testes em um turno e em uma máquina diferentes, como saber se o resultado veio do compilador? → 1º: aula03.pdf p.13-16 (score 0.8387)
  - q27 [termo] O que é validade de construto? → 1º: aula02.pdf p.11-13 (score 0.8421)
  - q32 [parafrase] O que meu trabalho precisa ter para ser bem avaliado? → 1º: aula02.pdf p.7-9 (score 0.8338)
