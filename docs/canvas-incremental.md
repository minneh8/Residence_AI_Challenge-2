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
- `PADROES_NAO_CONTEUDO` (`src/rag/extracao.py`) tira do índice os arquivos de listas, exercícios e roteiros. Eles são baixados normalmente, só não são indexados. *(Removido na etapa 3, 23/11: todas as categorias entram no índice e o filtro é feito na busca.)*
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

## Progresso 17/11

### Diagnóstico dos outros dois cursos

- **93511 (Gerenciamento de Projetos de ES):** **não usa módulos** — todos os 9 arquivos
  ficam "sem módulo". São os livros **PMBOK de ~70 MB** (`guia-pmbok-7-portugues.pdf`
  ~70 MB e `pmbok-6-portugues.pdf` ~68 MB), fora `.docx` de templates/modelos e um
  `APS`/`modelo` de gestão de risco.
- **93532 (Manutenção e Evolução de Software):** tem **8 módulos nomeados por data**
  ("Aula 03/08", "Aula 10/08", …, mais "Qualidade", "REENGENHARIA DE PROCESSOS",
  "PROVA ORAL"). O **Pressman** (`Engenharia_de_Software_7ed_PRESSMAN…pdf`, **6,9 MB**)
  está no módulo **"Qualidade"**. A maioria do material de aula aqui é `.pptx`.

### Ordenação, paginação e formatos

- A ordenação por **`updated_at` (order=desc)** foi **validada entre páginas**: rodando
  `diagnostico_canvas.py --curso 93527 --per-page 5 --sort updated_at`, a lista saiu em
  3 páginas (5+5+4) toda decrescente, sem repetição e sem faltar arquivo.
- Para forçar isso, o `diagnostico_canvas.py` monta o `PaginatedList` na mão: o
  **`per_page` é ignorado pelo canvasapi 3.6.0 em `get_files`** (ele empacota tudo em
  `_kwargs` e o `PaginatedList` cai no default `per_page=100`).
- **Slides `.pptx` ficam fora do download** (continua só PDF), então em 93532 boa parte
  dos slides não é baixada nem indexada hoje.

### Filtro de cursos

- **PROFOCO (53876) entrou no filtro** (`IGNORED_KEYWORDS` ganhou `profoco`). A comparação
  agora é feita sobre o **nome do curso normalizado (minúsculas, sem acento)**, e as
  grafias acentuadas duplicadas (`atualização`, `orientações`) foram removidas da lista.
- Regressão: dos 13 cursos que passavam antes, restam **12** (PROFOCO removido; os demais
  seguem).

### Classificador por regras (`src/agente_canvas/classificador.py`)

- Classificador por regras (sem LLM) com categorias **slides, listas, trabalho, livros,
  indefinido** e `origem` indicando a regra que decidiu. Testes offline em
  `tests/test_classificador.py`: **22 casos reais** do diagnóstico + **2 sintéticos**
  (páginas e indefinido) + **5 sintéticos** de 23/11 (camada de módulo e palavras
  inteiras), 29 no total.
- **21 dos 22 casos reais são decididos pelas regras.** O único que escapa é
  **"Material de Apoio GP - ENG_SOFT.pdf"**: sem palavra de livro, sem módulo, 9 MB
  (< 20 MB) e sem contagem de páginas, ele fica **`indefinido`** pelas regras. O
  **gabarito final dele é `livros`**, a ser decidido **pela regra de páginas depois do
  download** (quando a contagem de páginas existir) **ou pela camada de LLM**.

## Progresso 23/11

### Fechamento do dia

- **Classificação:** 22 de 22 PDFs dos 3 cursos classificados pelas regras. "Material de
  Apoio GP - ENG_SOFT.pdf" vira `livros` por `paginas>100` (118 páginas) depois do
  download. A LLM foi testada à parte com
  `scripts/testar_classificador_llm.py --forcar-llm`: `livros`, confiança 0,9, 650
  tokens, 1,4 s.
- **Teste real no 93527:**
  - 1ª execução: 5 PDFs baixados e 8 migrados sem baixar, 24 requisições ao Canvas;
  - 2ª execução: 0 downloads, 4 requisições, parada antecipada no 1º item e
    reindexação pulada.
- **Erro da API da LLM:** o arquivo fica pendente (`pendentes_llm`), não é gravado no
  catálogo e o estado do aluno não avança; é tentado de novo na próxima sincronização.
- **RAG:** todas as categorias no índice, `buscar(..., categorias=[...])` filtra por
  categoria e o Tutor busca só em slides. Avaliação oficial (18 perguntas, `rag_j1_s0`):

  | Variante | k | HitRate@k | Recall@k | Precision@k | MRR |
  |---|---|---|---|---|---|
  | sem filtro | 3 | 0,722 | 0,630 | 0,296 | 0,630 |
  | sem filtro | 5 | 0,722 | 0,667 | 0,200 | 0,630 |
  | `--categorias slides` | 3 | 0,722 | 0,630 | 0,296 | 0,630 |
  | `--categorias slides` | 5 | 0,722 | 0,667 | 0,200 | 0,630 |
  | Referência: só aula00 a aula04 | 5 | 0,778 | - | - | 0,657 |
  | Referência: 12 PDFs, listas no topo | 5 | 0,722 | - | - | 0,630 |

- **Próxima etapa:**
  - interface Streamlit: botão "Sincronizar" com o resumo da sincronização, materiais
    por categoria e campo de tema → resumo do Tutor com citações;
  - orquestrador mínimo: supervisor com estado compartilhado e roteamento por regra;
  - medir o tempo só da sincronização (separado da indexação e do Tutor).

### Ajustes no classificador

- **Camada de módulo por categoria.** Antes, qualquer palavra conhecida no módulo
  devolvia `slides`. Agora cada conjunto decide a sua categoria:
  lista/exercicio/atividade/entrega → listas; roteiro/trabalho/projeto → trabalho;
  livro/bibliografia/leitura → livros; aula/slide → slides. Um módulo neutro
  ("Qualidade", "Custos", "PROVA ORAL") não decide e passa para a próxima camada. O
  padrão de edição deixou de valer no módulo.
- **Palavras inteiras.** O nome e o módulo são normalizados e divididos em palavras
  (por camelCase, por caractere não alfanumérico e entre letra e dígito: `aula03` →
  `aula 03`). Cada palavra aceita o plural em "s" (`slides`, `exercicios`). Assim `aps`
  não casa mais com "etapas"/"mapas". Exceções: `ex_` continua como **prefixo** do nome,
  e a edição (`7ed`, `7a ed`, `edicao`) continua por regex.
- Os esperados dos 22 casos reais e dos 2 sintéticos antigos não mudaram.
- O diagnóstico dos 3 cursos não pôde ser refeito em 23/11. A causa: o `.env` estava
  com o host de exemplo `canvas.instructure.com`, que não é a instância da instituição
  e responde 503. O `CanvasService` não tem mais URL padrão: sem `CANVAS_API_URL` ele
  encerra com "CANVAS_API_URL não definido" em vez de cair no modo offline.
- `scripts/classificar_logs.py` aplica o classificador a todos os PDFs dos logs
  `data/logs/diagnostico_<curso>.json` e destaca os indefinidos.

### Classificação dos 22 PDFs dos 3 cursos

Diagnóstico refeito em 23/11 com o host certo (`CANVAS_API_URL` da instituição),
seguido de `scripts/classificar_logs.py 93527 93511 93532` (páginas = None). Os 3
cursos têm **22 PDFs**, exatamente os 22 casos reais do teste. O restante de 93511 e
93532 é `.docx`/`.pptx`, que fica fora do download.

| arquivo | curso | categoria | origem |
|---|---|---|---|
| aula00.pdf … aula08.pdf (9) | 93527 | slides | modulo:aula |
| ex_aula_semana6.pdf | 93527 | listas | nome:ex_ |
| ex_aula03.pdf | 93527 | listas | nome:ex_ |
| lista_exercicios_01.pdf | 93527 | listas | nome:lista |
| PUCCampinas_MCEQ_RoteiroTrabalhoFinal.pdf | 93527 | trabalho | nome:roteiro |
| APS GESTAO DE RISCO GP.pdf | 93511 | trabalho | nome:aps |
| guia-pmbok-7-portugues.pdf | 93511 | livros | nome:pmbok |
| **Material de Apoio GP - ENG_SOFT.pdf** | 93511 | **indefinido** | nenhuma |
| modelo Gestao de risco.pdf | 93511 | trabalho | nome:modelo |
| pmbok-6-portugues.pdf | 93511 | livros | nome:pmbok |
| A1 - Apresentação Disciplina 2026-2.pdf | 93532 | slides | modulo:aula |
| A2 - Evolução de Software e Leis de Lehman.pdf | 93532 | slides | modulo:aula |
| A3 - Tipos de Manutenção de Software.pdf | 93532 | slides | modulo:aula |
| Engenharia_de_Software_7ed_PRESSMAN (1)_compressed.pdf | 93532 | livros | nome:edicao |

**Só "Material de Apoio GP - ENG_SOFT.pdf" vai para a camada de LLM.** Os outros 21
são decididos pelas regras.

### Merge da origin/testes

- A `origin/testes` (Lucas) entrou na branch: testes do Canvas e do Tutor, remoção do
  `converter.py` e contagem de páginas com `fitz`. A lógica de download dele (pastas
  `conteudo/` e `listas/`, parada pelo nome) foi substituída na etapa 2, abaixo.

## Etapa 2: catálogo, download incremental e LLM (23/11)

### O que mudou

- **`src/agente_canvas/catalogo.py`**: catálogo do curso (`_arquivos.json`, chaveado pelo
  id do Canvas, com nome, nome_local, categoria, origem, updated_at, size, caminho,
  paginas, modulo e baixado_em/migrado_em) e estado do aluno
  (`data/canvas_state/<user_id>.json`). Toda gravação é atômica (`.tmp` + rename).
- **`CanvasService.sincronizar_curso`** substitui `fetch_and_save_course_data`,
  `CATEGORIAS_LISTAS`, `_classificar_e_mover_pdf` e `organizar_pdfs_existentes`:
  - lista com `sort=updated_at&order=desc` e itera página a página (sem `list()`); para
    no primeiro arquivo com `updated_at <= ultimo_updated_at` do aluno;
  - sem estado ou com `--completo`, percorre tudo;
  - mesmo id e `updated_at` no catálogo e arquivo no disco → só registra;
  - senão baixa para `.part`, conta páginas, classifica e move para
    `data/raw/<id>/<categoria>/<nome>` (`_<file_id>` no nome se outro id já usa o nome);
  - atualização com o mesmo nome mantém a categoria (não chama a LLM de novo);
  - `get_course`, `get_files`, `get_modules`, `get_assignments` e o download passam por
    retentativas; 401 num curso vira aviso e o fluxo segue para o próximo curso.
- **Migração**: PDFs fora do catálogo (soltos na raiz, em `conteudo/` ou `listas/` da
  versão anterior) que casam pelo nome com a listagem do Canvas são movidos para a pasta
  da categoria e registrados sem baixar. O modo offline não move mais arquivos.
- **Índice**: `indexar_curso` só é chamado se algo mudou no curso (ou se o curso ainda
  não está no índice). `listar_pdfs` é recursivo, o manifesto é chaveado pelo caminho
  relativo e a metadata `categoria` é o nome da subpasta. `arquivo` e `chunk_id` não
  mudaram.
- `graph.py` ganhou `--completo`; `--curso <id>` continua sincronizando só esse curso.

### Camada de LLM (`src/agente_canvas/classificador_llm.py`)

- Só para os casos `indefinido` das regras. Groq, mesmo cliente e modelo do Tutor,
  temperatura 0.
- Entrada: texto das 3 primeiras páginas (até 4000 caracteres, via `extrair_pdf`) mais
  nome, módulo e nº de páginas. Prompt curto com as categorias fechadas slides, listas,
  trabalho, livros e outros, pedindo só JSON.
- Validação com pydantic (`categoria` Literal, `confianca` 0–1, `justificativa`). JSON
  inválido ou confiança < 0,6 → `outros`, com `origem` `llm:json_invalido` ou
  `llm:confianca_baixa`. Aceito → `origem = "llm"`.
- O resultado aceito e os casos `json_invalido`/`confianca_baixa` ficam no catálogo e não
  são recalculados enquanto o `updated_at` não mudar.
- **Erro da API (`llm:erro_api`) não grava no catálogo**: o PDF não é movido, o estado do
  aluno não avança e o arquivo é tentado de novo na próxima sincronização (resumo:
  `pendentes_llm`).
- **Na prática, os 22 PDFs dos 3 cursos não chegam à LLM.** Com o download, as páginas são
  contadas e "Material de Apoio GP - ENG_SOFT.pdf" (118 páginas) vira `livros` pela regra
  `paginas>100`, como previsto. Forçando a LLM com
  `scripts/testar_classificador_llm.py --curso 93511 --arquivo "..." --forcar-llm` (baixa
  para uma pasta temporária e não grava nada), ela também respondeu `livros`, confiança
  0,9, em 1,4 s e 650 tokens.
- **Seção 5.1 da documentação**: deixa de dizer "não usa LLM". O agente Canvas passa a
  usar LLM **só nesse fallback**, enviando **apenas material público do curso** (texto
  inicial do arquivo, nome, módulo e nº de páginas), nunca dados do aluno.

### Decisões tomadas na implementação

- **Arquivo apagado do disco**: com parada antecipada, a listagem continua além do ponto
  de parada até reencontrar todos os ids do catálogo que sumiram do disco. Numa varredura
  completa, ids que sumiram do disco e não existem mais no Canvas saem do catálogo.
- **Migração só em varredura completa** (primeira sincronização do aluno ou `--completo`).
  Assim um PDF local sem par no Canvas não obriga a percorrer a lista toda em toda
  execução; ele fica onde está e é avisado.
- **Falha num arquivo** (não só interrupção) também impede gravar o estado, para a
  próxima execução não parar antes dele.
- O catálogo é gravado a cada arquivo; o estado, só no fim. Uma execução interrompida
  retoma registrando o que já foi baixado e baixando o resto.
- `pasta` não é usada na classificação (o classificador não tem camada de pasta e buscar
  as pastas custaria mais uma requisição por curso).
- `categoria` no índice é `raiz` para PDFs que ficaram soltos na pasta do curso.
- A contagem por categoria do resumo é a do catálogo inteiro do curso, não só da execução.

## Etapa 3: RAG filtrando por categoria (23/11)

- `buscar(pergunta, course_id, k=5, categorias=None)`: com `categorias`, filtra no
  Chroma com `$and` de `course_id` e `categoria $in categorias`.
- `PADROES_NAO_CONTEUDO` removido: todas as categorias entram no índice. O 93527
  reindexado tem 358 chunks (slides 299, listas 31, trabalho 28).
- **Tutor** busca só em `categorias=["slides"]`. **Gerador** deve usar `["listas"]` (ou
  listas + slides) quando entrar no grafo.
- Avaliação oficial (18 perguntas, `rag_j1_s0`): HitRate@5 0,722 e MRR 0,630, com ou
  sem o filtro de slides. Detalhes em `docs/DECISOES.md` e `avaliacao/resultados.md`.
- Risco: um curso sem slides em PDF (ex.: 93511, só livros e trabalhos) não tem trechos
  para o Tutor com o filtro `["slides"]`, e o Tutor responde "Matéria não indexada".

## Testes com todos os cursos (25/11)

Máquina nova: só o 93527 existia, na estrutura antiga (plana, aula00 a aula07, sem
catálogo). Backup em `data/_backup/<data-hora>/` antes de começar.

### Ferramentas novas

- `scripts/sincronizar.py [--curso ID] [--completo] [--sem-indexar]`: só o Agente
  Canvas, sem Tutor. Grava `data/logs/sync_<data-hora>.json` com as contagens por curso,
  requisições, MB baixados e tempo.
- `scripts/verificar_canvas.py [--curso ID] [--sem-canvas]`: 8 checagens de
  integridade (id em dois caminhos, sha256 duplicado, nome em duas categorias, catálogo ×
  disco, tamanho × `size` do Canvas, `.part`/`.tmp`, PDFs do Canvas fora do catálogo).
  `--snapshot <arq>` salva sha256 + mtime; `--comparar <a> <b>` lista o que mudou.

### Resultados

- **Rodada 1** (12 cursos): 91 novos, 8 migrados (93527), 128 pulados (não PDF),
  354 MB, 422 requisições, ~10 min. Duas falhas no 93501 (ver "bloqueados" abaixo).
- **Rodada 2**: 0 downloads, 4 requisições por curso, 27,6 s no total; parada no 1º
  item em todos os cursos com arquivos, exceto no 93501 (varredura completa por causa
  dos bloqueados, só registrando). `verificar_canvas.py`: 0 problemas;
  `--comparar snap1 snap2`: nenhum arquivo mudou.
- **Cenários no 93527**: apagado do disco → só ele recuperado; professor atualiza
  depois da última sincronização (estado em `updated_at(aula05) − 1 s`) → só o aula05
  atualizado, os mais recentes registrados, parada no aula04; entrada mais recente fora
  do catálogo e do estado → só ela baixada como nova; `--completo` → 13 registrados, 0
  downloads; outro aluno no mesmo PC (sem estado) → 13 "só registrados", 0 downloads.
- **Classificação** (99 PDFs): 54 por regras e 45 pela LLM, 0 pendentes. 8 em `outros`
  (planos de ensino, cronogramas, agenda, notas). 17 `livros` com menos de 100 páginas
  (a maioria capítulos/apostilas decididos pela LLM; ela foi inconsistente nos
  `Fund_Redes_Cap*` do 93501). Nenhum slide com mais de 150 páginas.
- **Indexação** (`rag_j1_s0`, CPU): 7.242 chunks em 9 cursos, ~40 min. O 93527 voltou
  aos 358 chunks (slides 299, listas 31, trabalho 28). Livros dominam o índice (5.867).

| curso | chunks | tempo (s) |
|---|---|---|
| 93527 | 358 | 100 |
| 93522 | 0 | 0,1 |
| 93532 | 1.774 | 693 |
| 93496 | 656 | 203 |
| 94896 | 34 | 25 |
| 93491 | 13 | 16 |
| 94158 | 284 | 49 |
| 93501 | 424 | 61 |
| 93516 | 2.348 | 790 |
| 93511 | 1.351 | 475 |

### Mudança no agente: arquivos bloqueados para o aluno

- No 93501, dois PDFs de um **módulo não publicado** vêm na listagem com
  `locked_for_user: true` e sem `url`; o download dava 404, gastava ~17 s em
  retentativas e contava como falha.
- Agora vão para `resumo["bloqueados"]`, sem tentar baixar. Como `pendentes_llm`, seguram
  o estado do aluno, para serem vistos de novo quando o módulo for publicado. A regra de
  parada não mudou. Teste: `test_bloqueado_para_o_aluno_nao_baixa_e_segura_o_estado`.
- Efeito colateral: enquanto houver bloqueados, o curso faz varredura completa em toda
  sincronização (mesmas 4 requisições, nada é baixado).

### Pendências da classificação

Mudanças nas regras do `classificador.py` e nos esperados dos testes precisam ser
mostradas antes ao usuário.

1. **"modelo" e "guia" como sinais fracos, depois de aula/capítulo.** Hoje
   `nome:modelo` vence "aula": "Aula 07 - Qualidade em Software - Modelos e Normas" e
   "Aula 12 - Modelo da Qualidade CMMI" (93496), e "Fund_Redes_Cap02 - Modelo OSI" e
   "RCCD_Cap02 - Modelo OSI" (93501) viraram `trabalho`. `nome:guia` mandou
   "ApostilaGuiaESP32EBook.pdf" (47 p.) para `livros`. Proposta: "modelo"/"guia" só
   decidem se o nome não tiver aula/slide/capítulo (`cap`, `capitulo`).
2. **Regra de documentos administrativos → `outros`.** Plano de ensino, cronograma,
   agenda, média/notas e boas-vindas. Hoje dependem da LLM, e "Plano Ensino PI_II.pdf"
   (94896) virou `slides` pela regra `modulo:aula`; "BOAS VINDAS.pdf" (93491) virou
   `slides` pela LLM.
3. **Capítulos `Fund_Redes_*` inconsistentes (93501).** São todos do mesmo material, mas
   a LLM pôs Cap04 e Cap07 em `slides` e Cap00, 01a, 01b, 03, 05b, 06 e 09 em `livros`
   (o Cap06 tem 6 páginas). Arquivos da mesma série deveriam cair na mesma categoria.
4. **Definição de "livros".** 17 `livros` têm menos de 100 páginas (capítulos avulsos,
   apostilas, tutoriais e artigos). Decidir se "livros" é livro inteiro/apostila
   (material de referência longo) e para onde vão capítulos, tutoriais e artigos.
5. **Melhorar o prompt da LLM e reclassificar os 99 PDFs sem baixar.** O prompt deve
   trazer a definição das categorias (itens 2 a 4) e exemplos. A reclassificação deve ler
   os PDFs já no disco e atualizar categoria/origem no catálogo, movendo o arquivo de
   pasta, sem novo download (45 dos 99 foram decididos pela LLM).
6. **Limitação: OCR do 93522.** Os 7 PDFs de aula são só imagem (0 caracteres, ~2
   imagens por página): o curso tem 0 chunks no índice. Sem OCR, ele fica fora do RAG.

## Decisões

- **Classificação por camadas.** A primeira regra que decidir vale, nesta ordem: nome do arquivo (listas/trabalho/livros) → módulo → nome do arquivo (aula/slide) → número de páginas/tamanho → `indefinido` → LLM → `outros`. Não há camada de pasta: nenhum dos 3 cursos diagnosticados usa pastas (tudo fica em `course files`). Regras e LLM estão implementadas.
- **Parada antecipada.** O agente lista com `sort=updated_at&order=desc` e para no primeiro arquivo com `updated_at <= ultimo_updated_at` do estado do aluno. Acima desse ponto, compara **id + updated_at** com o catálogo para decidir entre registrar e baixar.
- **Catálogo por curso** em `data/raw/<course_id>/_arquivos.json`, chaveado pelo **id do Canvas**. Guarda nome, categoria, tamanho, datas, pasta, módulo e caminho local.
- **Estado do aluno** em `data/canvas_state/<user_id>.json`, usando o id real de `get_current_user`.
- **Trabalho é uma categoria própria**, separada de listas.
- **`.docx` fica fora do download.** Continua valendo só PDF.

## Pendências

1. ~~Rodar o diagnóstico nos cursos 93511 e 93532.~~ Feito em 17/11.
2. ~~Testar a ordenação entre páginas com `--per-page 5 --sort updated_at`.~~ Feito em 17/11.
3. ~~Refazer o diagnóstico dos 3 cursos e aplicar o classificador a todos os PDFs.~~ Feito em 23/11.
4. ~~Implementar a camada de LLM e o download incremental.~~ Feito em 23/11 (etapa 2).
5. O curso **96848** não pertence a esta conta. Ele só aparece no `COURSE_MAP_OFFLINE` de `node.py`.
6. ~~Decidir o destino do `PADROES_NAO_CONTEUDO`.~~ Removido na etapa 3 (23/11).
7. **Gerador:** quando entrar no grafo, deve chamar `buscar(..., categorias=["listas"])`
   (ou `["listas", "slides"]`, para gerar questões no estilo das listas com o conteúdo
   das aulas). Hoje ele não está no grafo.

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

## Interface (Streamlit) — etapa 4

Interface web que junta Canvas, Tutor e Gerador numa única tela.

### Como rodar

```powershell
.\.venv\Scripts\streamlit.exe run app/streamlit_app.py
```

Abre em `http://localhost:8501`. Precisa do `.env` preenchido (`CANVAS_API_KEY`,
`CANVAS_API_URL`, `GROQ_API_KEY`) e do curso já em `data/raw/<id>/` com índice no
Chroma (rode a sincronização ou `python src/graph.py --curso <id> --tema ...` antes).

### Arquitetura

- **`app/streamlit_app.py`** só conhece **`src/interface/acoes.py`**; não importa os
  agentes diretamente.
- **`executar_acao(action, course_id, tema, quantidade, forcar)`** monta o `GlauxState`,
  decide o plano (quais agentes rodam, na ordem) e mede o tempo de cada etapa. Devolve
  `agentes` (ordem), `tempos` (por agente), `tempo_sincronizacao` (só o Canvas),
  `resultados` (por agente) e `erro` (mensagem amigável ou `None`).
- As ações usam **exatamente** os valores de `state.action` do agente orquestrador
  (`origin/orquestrador`): `SINCRONIZAR_CANVAS`, `GERAR_CRONOGRAMA`, `GERAR_RESUMO`,
  `GERAR_QUESTOES`, `FLUXO_COMPLETO`. Enquanto o nó do orquestrador não entra no
  `graph.py`, é a própria `executar_acao` que roteia; quando entrar, ela passa a só
  definir `state.action` e chamar o grafo (documentado no topo de `acoes.py`).
- O plano segue a lógica do `OrchestratorService` (pula o Canvas quando já há dados
  locais, salvo "forçar varredura completa"), com uma diferença: **`GERAR_QUESTOES`
  não passa pelo Tutor** — o Gerador lê o RAG direto e não depende do resumo.
- O modelo de embeddings E5 é carregado uma vez via `st.cache_resource`.
- Erros viram mensagens claras, sem stack trace na tela: token inválido, `CANVAS_API_URL`
  ausente, Canvas fora do ar, Groq indisponível e curso sem índice.

### O que cada parte faz

- **Barra lateral:** usuário autenticado (nome vindo do Canvas, o token nunca aparece);
  seleção do curso (pastas em `data/raw/` + botão "Listar cursos do Canvas" para trazer
  os nomes); botão "Sincronizar Canvas" com a opção "Forçar varredura completa".
- **Resultado da sincronização:** novos, atualizados, migrados, pulados, pendentes da LLM,
  contagem por categoria, requisições ao Canvas e tempo da sincronização.
- **Aba Materiais:** arquivos do `_arquivos.json` agrupados por categoria, com nome,
  páginas e origem da classificação (regra ou LLM).
- **Aba Resumo:** campo de tema → resumo do Tutor em markdown com as citações inline e a
  lista de fontes (arquivo e página) logo abaixo.
- **Aba Questões:** tema + quantidade → questões do Gerador (enunciado, alternativas,
  resposta correta e o trecho de referência citado).
- **Aba Prazos:** tarefas do `assignments.json` ordenadas por data, destacando as dos
  próximos 7 dias.
- **Rodapé de cada ação:** "Agentes executados: Canvas → Tutor …" com o tempo de cada um.

### Tempo medido (curso 93527, máquina de origem, CPU)

- **Sincronização** (sem downloads, 4 requisições ao Canvas): **~3,9 s**.
- **Resumo** de "hipótese nula" (só Tutor, RAG + Groq): **~12 s**.
- **Questões** (3 questões, só Gerador, RAG + Groq): **~2 s**.

A primeira busca do processo inclui a carga do modelo E5 (~1,1 GB), fora desses tempos.
