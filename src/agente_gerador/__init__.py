"""Agente Gerador de Questões do Glaux: questões a partir do material das disciplinas.

Uso, a partir da raiz do projeto (a pasta que tem src/ e prompts/):

    from src.agente_gerador import gerar_questoes

    resultado = gerar_questoes("overfitting", course_id=123, quantidade=5)
    if resultado.status == "ok":
        for questao in resultado.questoes:
            print(questao.enunciado)
    else:
        print(resultado.mensagem)  # "sem_material" ou "erro"

A pasta usa underline (agente_gerador), e não hífen como agente-abnt e
agente-canvas, para poder ser importada normalmente (from src.agente_gerador ...).
"""

from .service import gerar_questoes

__all__ = ["gerar_questoes"]
