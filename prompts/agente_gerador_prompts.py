"""Prompts do Agente Gerador de Questões.

PROMPT_SISTEMA_GERADOR traz as regras, o formato da resposta e um exemplo
fictício. Os dados do pedido (tema, quantidade, tipos e trechos do material)
vão separados, na mensagem do usuário, montada por montar_prompt_usuario().

O exemplo usa um tema alheio às disciplinas (fotossíntese) e um arquivo que não
existe (exemplo_ficticio.pdf). Se o modelo copiar o exemplo, a validação no
código recusa a resposta, porque esse arquivo nunca está entre os trechos.
"""

import json
from collections.abc import Sequence


def _json(dados) -> str:
    return json.dumps(dados, ensure_ascii=False, indent=2)


def montar_prompt_usuario(
    tema: str, quantidade: int, tipos: Sequence[str], trechos: Sequence[dict]
) -> str:
    """Monta a mensagem do usuário: os dados do pedido, cada um na sua tag.

    Dos trechos vão só arquivo, página e texto; o score fica de fora.
    """
    material = [
        {"arquivo": t["arquivo"], "pagina": t["pagina"], "texto": t["texto"]} for t in trechos
    ]
    return "\n".join(
        [
            f"<tema>{tema}</tema>",
            f"<quantidade>{quantidade}</quantidade>",
            f"<tipos>{json.dumps(list(tipos), ensure_ascii=False)}</tipos>",
            "<trechos>",
            _json(material),
            "</trechos>",
        ]
    )


FORMATO_RESPOSTA = {
    "questoes": [
        {
            "id": "q1",
            "tipo": "multipla_escolha",
            "enunciado": "...",
            "alternativas": {"A": "...", "B": "...", "C": "...", "D": "..."},
            "correta": "B",
            "assunto": "...",
            "trecho_referencia": {"arquivo": "...", "pagina": 3},
        },
        {
            "id": "q2",
            "tipo": "dissertativa",
            "enunciado": "...",
            "assunto": "...",
            "trecho_referencia": {"arquivo": "...", "pagina": 5},
        },
    ]
}

EXEMPLO_TEMA = "fotossíntese"
EXEMPLO_QUANTIDADE = 2
EXEMPLO_TIPOS = ("multipla_escolha", "dissertativa")
EXEMPLO_TRECHOS = [
    {
        "arquivo": "exemplo_ficticio.pdf",
        "pagina": 4,
        "texto": (
            "A fotossíntese ocorre nos cloroplastos. Nela, a energia da luz é usada para "
            "transformar gás carbônico e água em glicose, liberando oxigênio."
        ),
    }
]
EXEMPLO_SAIDA = {
    "questoes": [
        {
            "id": "q1",
            "tipo": "multipla_escolha",
            "enunciado": "Em qual estrutura da célula vegetal ocorre a fotossíntese?",
            "alternativas": {
                "A": "Mitocôndria",
                "B": "Cloroplasto",
                "C": "Ribossomo",
                "D": "Núcleo",
            },
            "correta": "B",
            "assunto": "local da fotossíntese",
            "trecho_referencia": {"arquivo": "exemplo_ficticio.pdf", "pagina": 4},
        },
        {
            "id": "q2",
            "tipo": "dissertativa",
            "enunciado": (
                "Explique como a energia da luz é usada na fotossíntese e quais "
                "substâncias entram e saem do processo."
            ),
            "assunto": "etapas da fotossíntese",
            "trecho_referencia": {"arquivo": "exemplo_ficticio.pdf", "pagina": 4},
        },
    ]
}

_EXEMPLO_ENTRADA = montar_prompt_usuario(
    EXEMPLO_TEMA, EXEMPLO_QUANTIDADE, EXEMPLO_TIPOS, EXEMPLO_TRECHOS
)

PROMPT_SISTEMA_GERADOR = f"""Você cria questões de estudo para alunos de graduação, a partir do \
material das disciplinas.

A mensagem do usuário traz:
- <tema>: o assunto das questões;
- <quantidade>: quantas questões criar, no total;
- <tipos>: os tipos permitidos, entre "multipla_escolha" e "dissertativa";
- <trechos>: uma lista JSON de trechos do material, cada um com "arquivo", "pagina" e "texto".

Regras:
1. Use somente o conteúdo entre <trechos> e </trechos>. Se o material não cobrir a questão, \
não crie a questão.
2. Crie exatamente a quantidade pedida em <quantidade>, usando só os tipos de <tipos>.
3. Cada questão se apoia em um trecho. Em "trecho_referencia", copie "arquivo" e "pagina" \
exatamente como estão nesse trecho. Não invente arquivo nem página, e não copie o texto do trecho.
4. Múltipla escolha: exatamente 4 alternativas, nas chaves "A", "B", "C" e "D". Uma única \
alternativa correta e distratores plausíveis. Sem "todas as anteriores". Em "correta", grave só a \
letra da alternativa correta.
5. Dissertativa: uma pergunta que exija explicar um conceito, não uma resposta de uma palavra.
6. Em "assunto", escreva o subtema da questão em poucas palavras.
7. Escreva em português do Brasil.
8. Responda somente com o JSON, sem nenhum texto antes ou depois.

Formato da resposta (os "..." e os números são só marcadores):
{_json(FORMATO_RESPOSTA)}

Exemplo fictício, só para mostrar a forma. Não reutilize o conteúdo dele.

Entrada:
{_EXEMPLO_ENTRADA}

Resposta:
{_json(EXEMPLO_SAIDA)}
"""
