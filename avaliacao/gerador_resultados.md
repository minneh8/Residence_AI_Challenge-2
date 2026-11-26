# Avaliação do Agente Gerador de Questões

Gerado por `scripts/avaliar_gerador.py` em 2026-11-26. Curso 94256, 3 questões por tema, uma geração por tema. Modelo `openai/gpt-oss-20b`, `K_MINIMO=10`, `SCORE_MINIMO=0.8`. Busca: `buscar_para_gerador` (listas, slides e livros).
Só métricas automáticas: nenhum texto dos PDFs nem das questões.

| grupo | tema | status | chamadas | falhas | tempo (s) | correta antes → depois |
|---|---|---|---|---|---|---|
| dentro | modelo OSI | ok | 2 | quantidade errada | 8.1 | CC → AB |
| dentro | conceitos básicos de comunicação de dados | ok | 2 | quantidade errada | 2.2 | C → D |
| dentro | camada física | erro | 2 | quantidade errada, limite do Groq (429) | 1.7 | — |
| dentro | camada de enlace | ok | 1 | — | 1.3 | BC → CA |
| dentro | camada de rede | ok | 2 | outra | 2.5 | CC → BC |
| dentro | modalidades de comutação | ok | 2 | JSON recusado pelo Groq (400) | 2.3 | CB → AD |
| dentro | camada de transporte | ok | 1 | — | 1.4 | CC → AD |
| dentro | camada de aplicação | ok | 1 | — | 1.3 | BB → CB |
| dentro | gerência de redes | ok | 2 | quantidade errada | 2.9 | BB → CC |
| dentro | segurança de redes | erro | 2 | quantidade errada, quantidade errada | 2.6 | — |
| fora | fundamentos da qualidade | sem_material | 1 | — | 1.0 | — |
| fora | gestão da qualidade | sem_material | 1 | — | 0.8 | — |
| fora | normas ISO 9000 | sem_material | 1 | — | 0.9 | — |
| fora | norma ISO/IEC 25010 | sem_material | 1 | — | 1.0 | — |
| fora | norma ISO/IEC/IEEE 12207 | sem_material | 1 | — | 1.0 | — |
| fora | modelo de qualidade CMMI | sem_material | 1 | — | 0.9 | — |

## Resumo

- Temas de dentro (10): ok 8 · sem_material 0 · erro 2
- Temas de fora (6): ok 0 · sem_material 6 · erro 0 (o esperado é tudo em sem_material)
- ok na 1ª tentativa: 3 de 8
- Retentativas: 7 (motivos: quantidade errada 6, limite do Groq (429) 1, outra 1, JSON recusado pelo Groq (400) 1)
- Tempo por geração: média 2.0 s, máximo 8.1 s
- Letra correta antes de embaralhar: A 0 · B 6 · C 9 · D 0
- Letra correta depois de embaralhar: A 4 · B 3 · C 5 · D 3
