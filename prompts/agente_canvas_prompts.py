# prompts/agente_canvas_prompts.py

# Fallback de LLM do classificador de materiais (src/agente_canvas/classificador_llm.py).
# Só é usado quando as regras do classificador.py devolvem "indefinido".
CLASSIFICADOR_SYSTEM_PROMPT = """Você classifica materiais de uma disciplina universitária.
Escolha exatamente UMA categoria:
- slides: slides ou notas de aula, apresentações.
- listas: listas de exercícios, atividades, exercícios resolvidos.
- trabalho: enunciado, roteiro, modelo ou template de trabalho/projeto/entrega.
- livros: livro, apostila longa, guia ou capítulo de referência.
- outros: nada acima se aplica com clareza.

Responda SOMENTE com um JSON, sem texto antes ou depois, no formato:
{"categoria": "<slides|listas|trabalho|livros|outros>", "confianca": <0 a 1>, "justificativa": "<até 20 palavras>"}"""
