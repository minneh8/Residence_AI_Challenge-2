import os
import sys
import time
import json
import hashlib
from dotenv import load_dotenv
from openai import OpenAI

# Adiciona a raiz ao PYTHONPATH para possibilitar import do módulo de prompts
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# Importa o prompt isolado e os serviços desacoplados
from prompts.agente_abnt_prompts import PROMPT_SYSTEM_ABNT
from auth_service import autenticar_google_workspace
from docs_service import renderizar_layout_abnt_no_docs

# Carrega as variáveis do arquivo .env presente na raiz
load_dotenv(os.path.join(BASE_DIR, ".env"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DOCUMENT_ID = os.getenv("DOCUMENT_ID", "")

# Validação defensiva da chave de API
if not GROQ_API_KEY:
    raise ValueError(
        "A variável GROQ_API_KEY não foi encontrada! "
        "Verifique se o arquivo .env existe na raiz e contém: GROQ_API_KEY=gsk_..."
    )

client_groq = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY
)


def calcular_hash_texto(texto: str) -> str:
    """Calcula o hash MD5 do texto para evitar chamadas desnecessárias à API."""
    return hashlib.md5(texto.encode('utf-8')).hexdigest()


def processar_texto_com_ia(texto_rascunho: str) -> dict:
    """
    Submete o rascunho para a API da Groq utilizando o prompt importado.
    """
    modelos = [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b"
    ]

    for model_name in modelos:
        for tentativa in range(1, 4):
            try:
                print(f"[AGENTE ABNT] Processando com modelo {model_name} (tentativa {tentativa})...")
                
                response = client_groq.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": PROMPT_SYSTEM_ABNT},
                        {"role": "user", "content": f"Texto Rascunho Original Completo (Processar todos os parágrafos sem exceção):\n\n{texto_rascunho}"}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0
                )
                
                raw_text = response.choices[0].message.content.strip()
                data = json.loads(raw_text)
                print(f"[AGENTE ABNT] Sucesso no processamento com {model_name}!")
                return data

            except Exception as e:
                err_msg = str(e)
                print(f"[AGENTE ABNT] Aviso com modelo {model_name}: {err_msg}")
                if "404" in err_msg:
                    break
                time.sleep(2)

    raise RuntimeError("Não foi possível processar o rascunho com os modelos da Groq disponíveis.")


def monitorar_documento(document_id: str, intervalo_segundos: int = 15):
    """Monitora alterações no documento em tempo real."""
    if not document_id:
        raise ValueError("DOCUMENT_ID não está configurado no arquivo .env!")

    docs_service, drive_service = autenticar_google_workspace()
    
    print(f"\n=======================================================")
    print(f" AGENTE ABNT AUTOMÁTICO (MODULARIZADO)")
    print(f" Monitorando Documento ID: {document_id}")
    print(f"=======================================================\n")

    ultimo_hash = None

    try:
        while True:
            doc = docs_service.documents().get(documentId=document_id).execute()
            
            texto_rascunho = ""
            for item in doc.get('body', {}).get('content', []):
                if 'paragraph' in item:
                    for element in item.get('paragraph', {}).get('elements', []):
                        if 'textRun' in element:
                            texto_rascunho += element.get('textRun', {}).get('content', '')

            hash_atual = calcular_hash_texto(texto_rascunho)

            if ultimo_hash is None:
                ultimo_hash = hash_atual
                if texto_rascunho.strip():
                    print("[WATCHER] Executando primeira análise do documento...")
                    artigo_json = processar_texto_com_ia(texto_rascunho)
                    renderizar_layout_abnt_no_docs(docs_service, document_id, artigo_json)
                    
                    doc_modificado = docs_service.documents().get(documentId=document_id).execute()
                    txt_mod = "".join([el.get('textRun', {}).get('content', '') for item in doc_modificado.get('body', {}).get('content', []) if 'paragraph' in item for el in item.get('paragraph', {}).get('elements', []) if 'textRun' in el])
                    ultimo_hash = calcular_hash_texto(txt_mod)

            elif hash_atual != ultimo_hash:
                print("\n[EVENTO] Alteração de texto detectada no documento!")
                artigo_json = processar_texto_com_ia(texto_rascunho)
                renderizar_layout_abnt_no_docs(docs_service, document_id, artigo_json)
                
                doc_modificado = docs_service.documents().get(documentId=document_id).execute()
                txt_mod = "".join([el.get('textRun', {}).get('content', '') for item in doc_modificado.get('body', {}).get('content', []) if 'paragraph' in item for el in item.get('paragraph', {}).get('elements', []) if 'textRun' in el])
                ultimo_hash = calcular_hash_texto(txt_mod)

            time.sleep(intervalo_segundos)
    except KeyboardInterrupt:
        print("\n[SISTEMA] Monitoramento encerrado com sucesso.")


if __name__ == "__main__":
    monitorar_documento(DOCUMENT_ID, intervalo_segundos=15)