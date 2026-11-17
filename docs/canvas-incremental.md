# Agente Canvas: classificação e download incremental

Branch: `feature/canvas-incremental`. Diagnóstico feito em 2026-11-17.

## Objetivo

1. Classificar os materiais de cada curso nas categorias: **slides**, **listas**, **trabalho**, **livros** e **outros**.
2. Fazer o download **incremental por aluno**. A ideia é listar os arquivos do mais recente para o mais antigo e parar no primeiro que já foi baixado e não mudou.

## Estado atual do agente (`src/agente_canvas/`)

- `course.get_files()` é chamado sem ordenação, e o filtro de PDF é feito no cliente pela extensão do `display_name`.
- Para pular um arquivo, o agente só verifica `destino.exists()`, ou seja, compara o nome depois de `_nome_seguro`. Tamanho, `id` e `updated_at` não entram na comparação. Com isso:
  - um arquivo atualizado com o mesmo nome nunca é baixado de novo;
  - dois arquivos com o mesmo nome em pastas diferentes colidem.
- `user_id` é fixo, `"estudante_glaux"` (`src/graph.py`). `get_current_user` é usado só para validar o token, e o id não é guardado.
- Não existe registro dos downloads. A única referência é o que está em `data/raw/<course_id>/`.
- `PADROES_NAO_CONTEUDO` (`src/rag/extracao.py`) tira do índice os arquivos de listas, exercícios e roteiros. Eles são baixados normalmente, só não são indexados.
- `fetch_and_save_course_data` não tem retry. O retry com esperas de 2, 5 e 10 s cobre só `get_current_user` e `get_courses`. Uma falha em `get_course` ou `get_assignments` derruba a esteira.
- O RAG é chaveado pelo **nome do arquivo**:
  - metadata `arquivo`;
  - `chunk_id = "<course_id>:<arquivo>:<p>-<p_fim>"`;
  - manifesto `data/indice_manifest.json` com `{nome: mtime_ns}`.
- `listar_pdfs` **não é recursivo**: lê só o primeiro nível de `data/raw/<course_id>/`.
- Dependem de `data/raw/<course_id>/` com estrutura plana e dos nomes atuais dos arquivos:
  - `scripts/testar_integracao.py` (precisa de `aula03` p.15 no 93527);
  - `scripts/testar_extracao.py` e `scripts/testar_chunking.py`;
  - `scripts/avaliar.py` com `avaliacao/perguntas.json`;
  - o modo offline (`node.py`), o `TutorService` (`assignments.json`) e o `converter.py`.

## Diagnóstico do curso 93527

Comando: `scripts/diagnostico_canvas.py --curso 93527`. É somente leitura e grava o resultado em `data/logs/diagnostico_93527.json`.

- O curso tem **uma única pasta** (`course files`).
- Tem **3 módulos**, e eles batem com as categorias: "Slides de Aula" (slides), "Atividade de Entrega" (listas) e "Trabalho do Curso" (trabalho). Os 14 arquivos aparecem em algum módulo.
- `sort=created_at&order=desc` é **aceito**: a lista vem toda em ordem decrescente e traz o mesmo conjunto da listagem padrão.
- O canvasapi envia `per_page=100`, então a listagem custa **1 requisição por curso** quando o curso tem até 100 arquivos. Como os 14 arquivos couberam em uma página, a ordenação entre páginas ainda não foi testada.
- O diagnóstico inteiro fez 6 requisições: usuário, curso, pastas, módulos (com `include[]=items`) e as duas listagens de arquivos.
- O `updated_at` costuma ser **posterior** ao `created_at`, às vezes vários dias depois (por exemplo, `aula08.pdf`). Por isso, comparar só o nome não é suficiente.

| id | nome | tamanho | created_at | updated_at | módulo |
|---|---|---|---|---|---|
| 4252625 | aula00.pdf | 557.4KB | 2026-08-20T16:05:41Z | 2026-08-20T18:15:06Z | Slides de Aula |
| 4252644 | aula01.pdf | 310.3KB | 2026-08-20T16:18:55Z | 2026-09-03T18:09:56Z | Slides de Aula |
| 4290785 | aula02.pdf | 267.7KB | 2026-09-03T18:11:24Z | 2026-09-08T20:17:05Z | Slides de Aula |
| 4290793 | aula03.pdf | 390.9KB | 2026-09-03T18:12:06Z | 2026-09-10T14:11:25Z | Slides de Aula |
| 4390396 | aula04.pdf | 2.7MB | 2026-10-08T16:53:50Z | 2026-10-13T17:37:33Z | Slides de Aula |
| 4390397 | aula05.pdf | 490.8KB | 2026-10-08T16:53:58Z | 2026-10-13T17:37:34Z | Slides de Aula |
| 4390398 | aula06.pdf | 2.0MB | 2026-10-08T16:54:28Z | 2026-10-13T15:50:41Z | Slides de Aula |
| 4459201 | aula07.pdf | 593.9KB | 2026-11-06T12:47:19Z | 2026-11-11T14:54:44Z | Slides de Aula |
| 4477701 | aula08.pdf | 628.3KB | 2026-11-13T12:07:58Z | 2026-11-17T00:52:48Z | Slides de Aula |
| 4305463 | ex_aula_semana6.pdf | 445.9KB | 2026-09-10T14:11:00Z | 2026-10-08T16:58:30Z | Atividade de Entrega |
| 4291082 | ex_aula03.pdf | 334.0KB | 2026-09-03T20:46:56Z | 2026-09-04T16:10:14Z | Atividade de Entrega |
| 4390479 | lista_exercicios_01.pdf | 153.1KB | 2026-10-08T17:28:35Z | 2026-10-21T22:46:26Z | Atividade de Entrega |
| 4441375 | PUCCampinas_MCEQ_RoteiroTrabalhoFinal.pdf | 406.4KB | 2026-10-29T20:16:34Z | 2026-11-01T19:19:46Z | Trabalho do Curso |
| 4441376 | template_relatoriofinal.docx | 60.6KB | 2026-10-29T20:16:36Z | 2026-11-01T19:19:24Z | Trabalho do Curso |

Todos os arquivos estão na pasta `course files`.

## Decisões

- **Classificação por camadas, sem LLM.** A primeira regra que decidir vale, nesta ordem: módulo → pasta → nome do arquivo → tamanho/número de páginas → `outros`.
- **Parada antecipada.** O agente lista com `sort=updated_at&order=desc` e compara **id + updated_at** com o catálogo. Ele para no primeiro arquivo que já está registrado com o mesmo `updated_at`.
- **Catálogo por curso** em `data/raw/<course_id>/_arquivos.json`, chaveado pelo **id do Canvas**. Guarda nome, categoria, tamanho, datas, pasta, módulo e caminho local.
- **Estado do aluno** em `data/canvas_state/<user_id>.json`, usando o id real de `get_current_user`.
- **Trabalho é uma categoria própria**, separada de listas.
- **`.docx` fica fora do download.** Continua valendo só PDF.

## Pendências

1. Rodar o diagnóstico nos cursos **93511** (Gerenciamento de Projetos de ES) e **93532** (Manutenção e Evolução de Software).
2. Testar a ordenação entre páginas com `--per-page 5 --sort updated_at`. Para isso, o `diagnostico_canvas.py` precisa ganhar essas duas opções.
3. Depois disso, fazer a implementação.
4. O curso **96848** não pertence a esta conta. Ele só aparece no `COURSE_MAP_OFFLINE` de `node.py`.

## Como recriar o ambiente

```powershell
py -3.12 -m venv .venv          # usar 3.12: o chromadb 1.0.20 falhou fora dela no Windows
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
Copy-Item .env.example .env     # preencher CANVAS_API_KEY, CANVAS_API_URL e GROQ_API_KEY
.\.venv\Scripts\python.exe scripts\diagnostico_canvas.py --curso 93527
```

`.env`, `.venv` e `data/` ficam **fora do Git**. O `data/` (PDFs, índice do Chroma e logs) precisa ser recriado em cada máquina rodando o agente ou copiado manualmente.
