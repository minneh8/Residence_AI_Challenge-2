# Decisões do projeto

## RAG (busca nos PDFs das disciplinas)

- **Embeddings e índice:** modelo `intfloat/multilingual-e5-base` (E5, com os
  prefixos `query:` e `passage:`) e ChromaDB local em `data/chroma/`, com
  similaridade de cosseno e filtro por `course_id`.
- **Limpeza antes da indexação:** remove o rodapé de numeração do Beamer
  ("19 / 33") e descarta páginas curtas, capas (linhas repetidas em vários
  PDFs), separadores de seção, overlays do Beamer e páginas de navegação
  (conteúdo, objetivos da aula, próxima aula, referências, bibliografia).
- **Configuração escolhida: A (`rag_j1_s0`, 1 página por chunk) com k=5.**
  Na avaliação do curso 93527 (`scripts/avaliar.py`, 18 perguntas com
  resposta), A teve HitRate@5 de 0,778 e MRR de 0,657, contra 0,778 e 0,611
  de B (`rag_j3_s1`, 3 páginas com 1 de sobreposição). A também cita 1 página
  por resultado, contra cerca de 3,6 em B. k=5 continua como padrão porque
  não perde HitRate em relação a k=3 (0,778 nos dois), dá mais contexto ao
  agente e é o contrato já combinado com os agentes.
- **Métricas renomeadas (23/11):** o que o `avaliar.py` chamava de "Recall@k"
  é a fração de perguntas com pelo menos um trecho relevante no top-k, ou seja,
  **HitRate@k**. O nome foi corrigido no código, na saída e no histórico de
  `avaliacao/resultados.md`, sem mudar os números. Foram acrescentados
  **Recall@k** (páginas relevantes recuperadas / páginas relevantes do
  gabarito) e **Precision@k** (trechos relevantes / k), com média por pergunta.
- **Todas as categorias no índice, filtro na busca (23/11):** o
  `PADROES_NAO_CONTEUDO` (que tirava listas, exercícios e roteiros do índice
  pelo nome) foi removido. Cada chunk tem a metadata `categoria` (subpasta do
  Agente Canvas: slides, listas, trabalho, livros, outros) e
  `buscar(..., categorias=[...])` filtra no Chroma com `$and` de `course_id` e
  `categoria $in`. O Tutor busca só em `["slides"]`; o Gerador deve usar
  `["listas"]` (ou listas + slides).
- **Avaliação oficial (23/11), 13 PDFs (aula00 a aula08, 3 listas, 1
  roteiro), 18 perguntas, `rag_j1_s0`:** HitRate@5 0,722, Recall@5 0,667,
  Precision@5 0,200 e MRR 0,630, com ou sem o filtro de slides (os números são
  iguais). A queda em relação a 0,778 / 0,657 é uma pergunta (q14), que passou
  a perder para as aulas 05 a 08; as listas só aparecem no topo de perguntas
  que já erravam. Detalhes em `avaliacao/resultados.md`.

  | Variante | k | HitRate@k | Recall@k | Precision@k | MRR |
  |---|---|---|---|---|---|
  | sem filtro | 3 | 0,722 | 0,630 | 0,296 | 0,630 |
  | sem filtro | 5 | 0,722 | 0,667 | 0,200 | 0,630 |
  | `--categorias slides` | 3 | 0,722 | 0,630 | 0,296 | 0,630 |
  | `--categorias slides` | 5 | 0,722 | 0,667 | 0,200 | 0,630 |
  | Referência: só aula00 a aula04 | 5 | 0,778 | - | - | 0,657 |
  | Referência: 12 PDFs, listas no topo | 5 | 0,722 | - | - | 0,630 |
- **Escopo da avaliação:** o gabarito cobre só aula00 a aula04. As aulas 05
  a 08 estão no índice, mas ainda não têm perguntas no gabarito.
- **Sem score mínimo:** a busca sempre devolve os k mais próximos. As
  perguntas fora do conteúdo tiveram maior score de até 0,805, e a pergunta
  com resposta de menor score teve 0,833. A folga é pequena demais para um
  corte fixo, então cabe ao agente decidir se os trechos servem.
- **Gabarito:** gerado automaticamente (`avaliacao/perguntas.json`). Uma
  amostra de 6 perguntas foi verificada manualmente: 5 de 6 corretas (q01,
  q02, q04, q08 e q30). A q15 tinha gabarito incorreto e foi
  removida, porque o material das aulas 00 a 04 só menciona a aleatorização
  de passagem e não a explica. As demais seguem como `sugerida`.
- **Limitação conhecida:** perguntas de paráfrase, que não usam os termos do
  material (HitRate@5 de 0,714 em A, contra 1,000 nas diretas, na avaliação
  com aula00 a aula04).
