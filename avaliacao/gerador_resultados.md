# Avaliação do Agente Gerador de Questões

Gerado por `scripts/avaliar_gerador.py` em 2026-11-23. Curso 94256, 3 questões por tema, uma geração por tema. Modelo `openai/gpt-oss-20b`, `K_MINIMO=10`, `SCORE_MINIMO=0.8`.
Só métricas automáticas: nenhum texto dos PDFs nem das questões.

| grupo | tema | status | chamadas | falhas | tempo (s) | correta antes → depois |
|---|---|---|---|---|---|---|
| dentro | modelo OSI | sem_material | 1 | — | 7.5 | — |
| dentro | conceitos básicos de comunicação de dados | sem_material | 1 | — | 1.4 | — |
| dentro | camada física | ok | 1 | — | 1.6 | BC → CC |
| dentro | camada de enlace | ok | 1 | — | 1.6 | BC → BC |
| dentro | camada de rede | ok | 2 | JSON recusado pelo Groq (400) | 2.6 | BC → BD |
| dentro | modalidades de comutação | ok | 1 | — | 1.3 | BB → AC |
| dentro | camada de transporte | ok | 1 | — | 1.5 | BB → DC |
| dentro | camada de aplicação | ok | 1 | — | 1.2 | BD → DA |
| dentro | gerência de redes | erro | 2 | quantidade errada, quantidade errada | 2.4 | — |
| dentro | segurança de redes | erro | 2 | quantidade errada, quantidade errada | 2.0 | — |
| fora | fundamentos da qualidade | sem_material | 1 | — | 0.9 | — |
| fora | gestão da qualidade | sem_material | 1 | — | 1.7 | — |
| fora | normas ISO 9000 | sem_material | 1 | — | 0.8 | — |
| fora | norma ISO/IEC 25010 | sem_material | 1 | — | 0.8 | — |
| fora | norma ISO/IEC/IEEE 12207 | sem_material | 1 | — | 0.8 | — |
| fora | modelo de qualidade CMMI | sem_material | 1 | — | 1.3 | — |

## Resumo

- Temas de dentro (10): ok 6 · sem_material 2 · erro 2
- Temas de fora (6): ok 0 · sem_material 6 · erro 0 (o esperado é tudo em sem_material)
- ok na 1ª tentativa: 5 de 6
- Retentativas: 3 (motivos: quantidade errada 4, JSON recusado pelo Groq (400) 1)
- Tempo por geração: média 1.8 s, máximo 7.5 s
- Letra correta antes de embaralhar: A 0 · B 8 · C 3 · D 1
- Letra correta depois de embaralhar: A 2 · B 2 · C 5 · D 3
