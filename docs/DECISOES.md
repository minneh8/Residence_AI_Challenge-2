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
  resposta), A teve Recall@5 de 0,778 e MRR de 0,657, contra 0,778 e 0,611
  de B (`rag_j3_s1`, 3 páginas com 1 de sobreposição). A também cita 1 página
  por resultado, contra cerca de 3,6 em B. k=5 continua como padrão porque
  não perde Recall em relação a k=3 (0,778 nos dois), dá mais contexto ao
  agente e é o contrato já combinado com os agentes.
- **Escopo da avaliação:** feita só com aula00 a aula04. As aulas 05 a 07
  ficaram fora e ainda não têm perguntas no gabarito.
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
  material (Recall@5 de 0,714 em A, contra 1,000 nas diretas).
