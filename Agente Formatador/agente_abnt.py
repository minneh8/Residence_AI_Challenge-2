import os
import time
import json
import hashlib
from google import genai
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive'
]

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
client_gemini = genai.Client(api_key=GEMINI_API_KEY)


def autenticar_google_workspace():
    """Autentica o usuário e retorna os serviços de API do Google Docs e Drive."""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    credentials_path = os.path.join(BASE_DIR, 'credentials.json')
    token_path = os.path.join(BASE_DIR, 'token.json')

    creds = None
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception:
            creds = None
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"[AUTENTICAÇÃO] Renovação falhou ({e}). Gerando novo acesso...")
                if os.path.exists(token_path):
                    os.remove(token_path)
                creds = None

        if not creds:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(f"Arquivo 'credentials.json' não encontrado em: {credentials_path}")
            
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    docs_service = build('docs', 'v1', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return docs_service, drive_service


def calcular_hash_texto(texto: str) -> str:
    """Calcula hash MD5 do texto para evitar chamadas desnecessárias à API."""
    return hashlib.md5(texto.encode('utf-8')).hexdigest()


def processar_texto_com_ia(texto_rascunho: str) -> dict:
    """Submete o rascunho para a API do Gemini estruturando a resposta em JSON sem duplicar o resumo."""
    prompt = f"""
Você é um Revisor Acadêmico Sênior especializado em Artigos Científicos.
Sua tarefa é analisar o rascunho fornecido, reescrever corrigindo TODA a ortografia e gramática, e estruturar a resposta ESTRITAMENTE como um objeto JSON.

O JSON deve seguir a seguinte estrutura exata:
{{
  "titulo_principal": "TÍTULO DO ARTIGO EM CAIXA ALTA E CORRIGIDO",
  "autores": "Nome do Autor ou Autores",
  "resumo": "Texto completo do resumo corrigido sem erros de acentuação.",
  "palavras_chave": "PALAVRAS-CHAVE: termo 1. termo 2. termo 3.",
  "elementos": [
    {{
      "tipo": "TITULO_SECAO" ou "SUBTITULO_SECAO" ou "PARAGRAFO" ou "CITACAO_LONGA" ou "REFERENCIA",
      "texto": "Texto do parágrafo ou título corrigido ortograficamente",
      "numeracao": "2." ou "2.1" ou "[1]" ou null
    }}
  ]
}}

REGRAS OBRIGATÓRIAS DE ESTRUTURAÇÃO:
1. O texto do resumo DEVE ficar no campo "resumo" do JSON. NÃO inclua o resumo nem o título "1. RESUMO" dentro do array "elementos".
2. As seções dentro de "elementos" devem começar A PARTIR DA INTRODUÇÃO numeradas normalmente: 2. INTRODUÇÃO, 3. DESENVOLVIMENTO, 3.1 Subtítulo, 4. CONCLUSÃO.
3. Na seção de REFERÊNCIAS ao final, numere cada item no formato [1], [2], [3]... em ordem alfabética.
4. Corrija 100% dos erros de grafia, pontuação e acentuação de todo o texto.
5. Responda APENAS o objeto JSON válido.

Texto Rascunho Original:
{texto_rascunho}
"""

    modelos = [
        "gemini-3.1-flash-lite",
        "gemini-flash-latest"
    ]

    for model_name in modelos:
        for tentativa in range(1, 4):
            try:
                print(f"[AGENTE ABNT] Processando com {model_name} (tentativa {tentativa})...")
                response = client_gemini.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                
                raw_text = response.text.strip()
                
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.startswith("```"):
                    raw_text = raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]

                data = json.loads(raw_text.strip())
                print(f"[AGENTE ABNT] Sucesso no processamento com {model_name}!")
                return data

            except Exception as e:
                err_msg = str(e)
                if "503" in err_msg or "UNAVAILABLE" in err_msg:
                    tempo_espera = tentativa * 3
                    print(f"[AGENTE ABNT] Modelo {model_name} ocupado (503). Aguardando {tempo_espera}s...")
                    time.sleep(tempo_espera)
                elif "404" in err_msg or "NOT_FOUND" in err_msg:
                    print(f"[AGENTE ABNT] Modelo {model_name} indisponível (404). Tentando próximo...")
                    break
                else:
                    print(f"[AGENTE ABNT] Erro ao processar com {model_name}: {e}")
                    time.sleep(1)

    raise RuntimeError("Não foi possível processar o rascunho com os modelos Gemini disponíveis.")


def renderizar_layout_abnt_no_docs(docs_service, document_id: str, artigo: dict):
    """Atualiza o conteúdo no Google Docs sem duplicação de seções."""
    print("[AGENTE ABNT] Reconstruindo texto no Google Docs...")
    
    doc = docs_service.documents().get(documentId=document_id).execute()
    body_content = doc.get('body', {}).get('content', [])
    end_index = body_content[-1].get('endIndex', 1) - 1

    requests = []

    # 1. Limpa o texto antigo
    if end_index > 1:
        requests.append({
            'deleteContentRange': {
                'range': {'startIndex': 1, 'endIndex': end_index}
            }
        })

    # 2. Monta a estrutura limpa
    titulo = artigo.get("titulo_principal", "").strip()
    autores = artigo.get("autores", "").strip()
    resumo = artigo.get("resumo", "").strip()
    palavras_chave = artigo.get("palavras_chave", "").strip()
    elementos = artigo.get("elementos", [])

    texto_gerado = f"{titulo}\n"
    texto_gerado += f"{autores}\n\n"
    texto_gerado += f"1. RESUMO\n{resumo}\n"
    texto_gerado += f"{palavras_chave}\n\n"

    for el in elementos:
        tipo = el.get("tipo", "PARAGRAFO")
        num = el.get("numeracao")
        txt = el.get("texto", "").strip()

        # Filtra elementos para evitar qualquer duplicação do resumo no loop
        if "resumo" in txt.lower() and (num in ["1.", "1"] or not num):
            continue

        if tipo in ["TITULO_SECAO", "SUBTITULO_SECAO", "REFERENCIA"] and num:
            texto_gerado += f"{num} {txt}\n"
        else:
            texto_gerado += f"{txt}\n"

    requests.append({
        'insertText': {
            'location': {'index': 1},
            'text': texto_gerado
        }
    })

    # Margens Oficiais ABNT: Superior 3cm, Esquerda 3cm, Inferior 2cm, Direita 2cm
    requests.append({
        'updateDocumentStyle': {
            'documentStyle': {
                'marginTop': {'magnitude': 3 * 28.35, 'unit': 'PT'},
                'marginLeft': {'magnitude': 3 * 28.35, 'unit': 'PT'},
                'marginBottom': {'magnitude': 2 * 28.35, 'unit': 'PT'},
                'marginRight': {'magnitude': 2 * 28.35, 'unit': 'PT'},
            },
            'fields': 'marginTop,marginLeft,marginBottom,marginRight'
        }
    })

    docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

    # 3. Estilização Visual
    print("[AGENTE ABNT] Aplicando estilos visuais...")
    doc_atualizado = docs_service.documents().get(documentId=document_id).execute()
    content = doc_atualizado.get('body', {}).get('content', [])

    style_requests = []

    for item in content:
        if 'paragraph' not in item:
            continue

        start_index = item.get('startIndex')
        end_index = item.get('endIndex')
        
        if start_index == end_index or (end_index - start_index <= 1):
            continue

        p_text = ""
        for el in item.get('paragraph', {}).get('elements', []):
            if 'textRun' in el:
                p_text += el.get('textRun', {}).get('content', '')
        
        p_text_clean = p_text.strip()

        # A. TÍTULO PRINCIPAL (14pt, Negrito, Centralizado)
        if p_text_clean == titulo:
            style_requests.append({
                'updateTextStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'textStyle': {'weightedFontFamily': {'fontFamily': 'Arial'}, 'fontSize': {'magnitude': 14, 'unit': 'PT'}, 'bold': True},
                    'fields': 'weightedFontFamily,fontSize,bold'
                }
            })
            style_requests.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'paragraphStyle': {'alignment': 'CENTER', 'lineSpacing': 150, 'spaceBelow': {'magnitude': 12, 'unit': 'PT'}},
                    'fields': 'alignment,lineSpacing,spaceBelow'
                }
            })

        # B. AUTORES (11pt, Itálico, Centralizado)
        elif p_text_clean == autores:
            style_requests.append({
                'updateTextStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'textStyle': {'weightedFontFamily': {'fontFamily': 'Arial'}, 'fontSize': {'magnitude': 11, 'unit': 'PT'}, 'italic': True},
                    'fields': 'weightedFontFamily,fontSize,italic'
                }
            })
            style_requests.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'paragraphStyle': {'alignment': 'CENTER', 'lineSpacing': 150, 'spaceBelow': {'magnitude': 18, 'unit': 'PT'}},
                    'fields': 'alignment,lineSpacing,spaceBelow'
                }
            })

        # C. PALAVRAS-CHAVE (12pt, Sem recuo na 1ª linha)
        elif p_text_clean.startswith("PALAVRAS-CHAVE"):
            style_requests.append({
                'updateTextStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'textStyle': {'weightedFontFamily': {'fontFamily': 'Arial'}, 'fontSize': {'magnitude': 12, 'unit': 'PT'}, 'bold': True},
                    'fields': 'weightedFontFamily,fontSize,bold'
                }
            })
            style_requests.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'paragraphStyle': {'alignment': 'JUSTIFIED', 'lineSpacing': 150, 'indentFirstLine': {'magnitude': 0, 'unit': 'PT'}, 'spaceBelow': {'magnitude': 12, 'unit': 'PT'}},
                    'fields': 'alignment,lineSpacing,indentFirstLine,spaceBelow'
                }
            })

        # D. TÍTULOS DE SEÇÃO E SUBSEÇÃO NUMERADOS (1. RESUMO, 2. INTRODUÇÃO, etc.)
        elif p_text_clean and (p_text_clean[0].isdigit() or p_text_clean.startswith("REFERÊNCIAS")):
            style_requests.append({
                'updateTextStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'textStyle': {'weightedFontFamily': {'fontFamily': 'Arial'}, 'fontSize': {'magnitude': 12, 'unit': 'PT'}, 'bold': True},
                    'fields': 'weightedFontFamily,fontSize,bold'
                }
            })
            style_requests.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'paragraphStyle': {'alignment': 'START', 'lineSpacing': 150, 'spaceAbove': {'magnitude': 12, 'unit': 'PT'}, 'spaceBelow': {'magnitude': 6, 'unit': 'PT'}, 'indentFirstLine': {'magnitude': 0, 'unit': 'PT'}},
                    'fields': 'alignment,lineSpacing,spaceAbove,spaceBelow,indentFirstLine'
                }
            })

        # E. CITAÇÃO LONGA (+3 linhas: Recuo de 4cm, 10pt, Espaçamento simples)
        elif len(p_text_clean) > 180 and ("\"" in p_text_clean or "p." in p_text_clean or "(" in p_text_clean):
            style_requests.append({
                'updateTextStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'textStyle': {'weightedFontFamily': {'fontFamily': 'Arial'}, 'fontSize': {'magnitude': 10, 'unit': 'PT'}},
                    'fields': 'weightedFontFamily,fontSize'
                }
            })
            style_requests.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'paragraphStyle': {'alignment': 'JUSTIFIED', 'lineSpacing': 100, 'indentStart': {'magnitude': 4 * 28.35, 'unit': 'PT'}, 'indentFirstLine': {'magnitude': 0, 'unit': 'PT'}, 'spaceBelow': {'magnitude': 6, 'unit': 'PT'}},
                    'fields': 'alignment,lineSpacing,indentStart,indentFirstLine,spaceBelow'
                }
            })

        # F. REFERÊNCIAS BIBLIOGRÁFICAS [1], [2] (11pt)
        elif p_text_clean.startswith("["):
            style_requests.append({
                'updateTextStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'textStyle': {'weightedFontFamily': {'fontFamily': 'Arial'}, 'fontSize': {'magnitude': 11, 'unit': 'PT'}},
                    'fields': 'weightedFontFamily,fontSize'
                }
            })
            style_requests.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'paragraphStyle': {'alignment': 'START', 'lineSpacing': 100, 'indentFirstLine': {'magnitude': 0, 'unit': 'PT'}, 'spaceBelow': {'magnitude': 6, 'unit': 'PT'}},
                    'fields': 'alignment,lineSpacing,indentFirstLine,spaceBelow'
                }
            })

        # G. PARÁGRAFO PADRÃO E TEXTO DO RESUMO
        # (12pt, Justificado, Espaçamento 1,5, Recuo na 1ª linha 1,25cm)
        else:
            style_requests.append({
                'updateTextStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'textStyle': {'weightedFontFamily': {'fontFamily': 'Arial'}, 'fontSize': {'magnitude': 12, 'unit': 'PT'}},
                    'fields': 'weightedFontFamily,fontSize'
                }
            })
            style_requests.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'paragraphStyle': {'alignment': 'JUSTIFIED', 'lineSpacing': 150, 'indentFirstLine': {'magnitude': 1.25 * 28.35, 'unit': 'PT'}, 'spaceBelow': {'magnitude': 0, 'unit': 'PT'}},
                    'fields': 'alignment,lineSpacing,indentFirstLine,spaceBelow'
                }
            })

    if style_requests:
        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': style_requests}).execute()
        print(" -> [SUCESSO] Documento formatado com Resumo único e alinhado!")


def monitorar_documento(document_id: str, intervalo_segundos: int = 15):
    """Monitora alterações no documento."""
    docs_service, drive_service = autenticar_google_workspace()
    
    print(f"\n=======================================================")
    print(f" AGENTE ABNT AUTOMÁTICO - MONITORAMENTO ATIVO")
    print(f" Monitorando Documento ID: {document_id}")
    print(f" Pressione Ctrl+C para encerrar.")
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
    DOCUMENT_ID = "1RvnMyg-5O3i4s_iIgmwN61aHuesJjyV0a_0bFIUot0E"
    monitorar_documento(DOCUMENT_ID, intervalo_segundos=15)