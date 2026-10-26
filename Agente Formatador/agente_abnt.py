import os
import time
import json
from google import genai
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Escopos para ler e editar Google Docs e Drive
SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive.readonly'
]

# Inicializa o cliente oficial da Gemini API
# Certifique-se de ter a variável GEMINI_API_KEY configurada no seu ambiente
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "SUA_CHAVE")
client_gemini = genai.Client(api_key=GEMINI_API_KEY)


def autenticar_google_workspace():
    """Autentica o usuário e retorna os serviços de API do Google Docs e Drive."""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    credentials_path = os.path.join(BASE_DIR, 'credentials.json')
    token_path = os.path.join(BASE_DIR, 'token.json')

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(f"Arquivo de credenciais não encontrado em: {credentials_path}")
            
            # Carrega o cliente desktop corretamente
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    docs_service = build('docs', 'v1', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return docs_service, drive_service

def revisar_texto_com_gemini(texto_original: str) -> str:
    """Envia o conteúdo para a API do Gemini para revisar citações e referências ABNT."""
    prompt_system = """
    Você é um agente revisor especializado em normas ABNT.
    Sua tarefa é analisar o texto fornecido e ajustar:
    1. Formatação de referências bibliográficas ao final (autor em CAIXA ALTA, ordem alfabética, etc.).
    2. Citações diretas e indiretas (ex: SOBRENOME, ano, p. X).
    Retorne o texto ajustado mantendo o conteúdo original.
    """
    
    modelos = ["gemini-2.5-flash", "gemini-2.5-pro"]
    
    for model_name in modelos:
        try:
            response = client_gemini.models.generate_content(
                model=model_name,
                contents=f"{prompt_system}\n\nTexto original:\n{texto_original}"
            )
            return response.text
        except Exception as e:
            print(f"[AGENTE ABNT] Modelo {model_name} indisponível. Tentando próximo...")
            
    return texto_original


def aplicar_formatacao_abnt_docs(docs_service, document_id: str):
    """Aplica formatação estruturada de Artigo Científico ABNT (NBR 6022)."""
    
    # 1. Margens ABNT em Pontos (1 cm = 28.35 pt)
    requests = [
        {
            'updateDocumentStyle': {
                'documentStyle': {
                    'marginTop': {'magnitude': 3 * 28.35, 'unit': 'PT'},
                    'marginLeft': {'magnitude': 3 * 28.35, 'unit': 'PT'},
                    'marginBottom': {'magnitude': 2 * 28.35, 'unit': 'PT'},
                    'marginRight': {'magnitude': 2 * 28.35, 'unit': 'PT'},
                },
                'fields': 'marginTop,marginLeft,marginBottom,marginRight'
            }
        }
    ]

    doc = docs_service.documents().get(documentId=document_id).execute()
    content = doc.get('body').get('content', [])

    is_primeiro_paragrafo = True

    for item in content:
        if 'paragraph' in item:
            start_index = item.get('startIndex')
            end_index = item.get('endIndex')
            
            # Ignora linhas vazias
            if start_index == end_index or (end_index - start_index <= 1):
                continue

            # Extrai o texto do parágrafo
            p_text = ""
            for el in item.get('paragraph', {}).get('elements', []):
                if 'textRun' in el:
                    p_text += el.get('textRun', {}).get('content', '')
            
            p_text_clean = p_text.strip()
            heading_type = item.get('paragraph', {}).get('paragraphStyle', {}).get('namedStyleType', '')

            # --- A. TÍTULO PRINCIPAL DO ARTIGO ---
            if is_primeiro_paragrafo and not p_text_clean.lower().startswith("resumo"):
                requests.append({
                    'updateTextStyle': {
                        'range': {'startIndex': start_index, 'endIndex': end_index},
                        'textStyle': {
                            'weightedFontFamily': {'fontFamily': 'Arial'},
                            'fontSize': {'magnitude': 14, 'unit': 'PT'},
                            'bold': True
                        },
                        'fields': 'weightedFontFamily,fontSize,bold'
                    }
                })
                requests.append({
                    'updateParagraphStyle': {
                        'range': {'startIndex': start_index, 'endIndex': end_index},
                        'paragraphStyle': {
                            'alignment': 'CENTER',
                            'lineSpacing': 150,
                            'spaceBelow': {'magnitude': 12, 'unit': 'PT'}
                        },
                        'fields': 'alignment,lineSpacing,spaceBelow'
                    }
                })
                is_primeiro_paragrafo = False
                continue

            is_primeiro_paragrafo = False

            # --- B. SEÇÕES E TÍTULOS (HEADING 1, HEADING 2 ou Numeração 1., 2.) ---
            if 'HEADING' in heading_type or (p_text_clean and p_text_clean[0].isdigit() and '.' in p_text_clean[:4]):
                requests.append({
                    'updateTextStyle': {
                        'range': {'startIndex': start_index, 'endIndex': end_index},
                        'textStyle': {
                            'weightedFontFamily': {'fontFamily': 'Arial'},
                            'fontSize': {'magnitude': 12, 'unit': 'PT'},
                            'bold': True
                        },
                        'fields': 'weightedFontFamily,fontSize,bold'
                    }
                })
                requests.append({
                    'updateParagraphStyle': {
                        'range': {'startIndex': start_index, 'endIndex': end_index},
                        'paragraphStyle': {
                            'alignment': 'START', # Alinhado à esquerda
                            'lineSpacing': 150,
                            'spaceAbove': {'magnitude': 12, 'unit': 'PT'},
                            'spaceBelow': {'magnitude': 6, 'unit': 'PT'},
                            'indentFirstLine': {'magnitude': 0, 'unit': 'PT'}
                        },
                        'fields': 'alignment,lineSpacing,spaceAbove,spaceBelow,indentFirstLine'
                    }
                })
                continue

            # --- C. RESUMO / ABSTRACT / PALAVRAS-CHAVE ---
            if p_text_clean.lower().startswith("resumo") or p_text_clean.lower().startswith("abstract") or p_text_clean.lower().startswith("palavras-chave"):
                requests.append({
                    'updateTextStyle': {
                        'range': {'startIndex': start_index, 'endIndex': end_index},
                        'textStyle': {
                            'weightedFontFamily': {'fontFamily': 'Arial'},
                            'fontSize': {'magnitude': 10, 'unit': 'PT'} # Fonte menor (10pt)
                        },
                        'fields': 'weightedFontFamily,fontSize'
                    }
                })
                requests.append({
                    'updateParagraphStyle': {
                        'range': {'startIndex': start_index, 'endIndex': end_index},
                        'paragraphStyle': {
                            'alignment': 'JUSTIFIED',
                            'lineSpacing': 100, # Espaçamento simples (1.0)
                            'indentFirstLine': {'magnitude': 0, 'unit': 'PT'}, # Sem recuo na 1ª linha
                            'spaceBelow': {'magnitude': 6, 'unit': 'PT'}
                        },
                        'fields': 'alignment,lineSpacing,indentFirstLine,spaceBelow'
                    }
                })
                continue

            # --- D. CITAÇÕES LONGAS (Mais de 3 linhas / Bloco Recuado) ---
            if len(p_text_clean) > 200 and ("\"" in p_text_clean or "segundo" in p_text_clean.lower() or "(" in p_text_clean):
                # Aplicar recuo de citação longa (4 cm da margem esquerda)
                requests.append({
                    'updateTextStyle': {
                        'range': {'startIndex': start_index, 'endIndex': end_index},
                        'textStyle': {
                            'weightedFontFamily': {'fontFamily': 'Arial'},
                            'fontSize': {'magnitude': 10, 'unit': 'PT'}
                        },
                        'fields': 'weightedFontFamily,fontSize'
                    }
                })
                requests.append({
                    'updateParagraphStyle': {
                        'range': {'startIndex': start_index, 'endIndex': end_index},
                        'paragraphStyle': {
                            'alignment': 'JUSTIFIED',
                            'lineSpacing': 100,
                            'indentStart': {'magnitude': 4 * 28.35, 'unit': 'PT'}, # Recuo 4cm
                            'indentFirstLine': {'magnitude': 0, 'unit': 'PT'},
                            'spaceBelow': {'magnitude': 6, 'unit': 'PT'}
                        },
                        'fields': 'alignment,lineSpacing,indentStart,indentFirstLine,spaceBelow'
                    }
                })
                continue

            # --- E. PARÁGRAFO PADRÃO DO CORPO DO ARTIGO ---
            requests.append({
                'updateTextStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'textStyle': {
                        'weightedFontFamily': {'fontFamily': 'Arial'},
                        'fontSize': {'magnitude': 12, 'unit': 'PT'}
                    },
                    'fields': 'weightedFontFamily,fontSize'
                }
            })
            requests.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'paragraphStyle': {
                        'alignment': 'JUSTIFIED',
                        'lineSpacing': 150, # Espaçamento 1,5
                        'indentFirstLine': {'magnitude': 1.25 * 28.35, 'unit': 'PT'}, # Recuo ABNT 1,25cm
                        'spaceBelow': {'magnitude': 0, 'unit': 'PT'}
                    },
                    'fields': 'alignment,lineSpacing,indentFirstLine,spaceBelow'
                }
            })

    if requests:
        docs_service.documents().batchUpdate(
            documentId=document_id,
            body={'requests': requests}
        ).execute()
        print(" -> Estrutura e estilos visuais de Artigo Científico ABNT aplicados com sucesso!")

def executar_agente_abnt(docs_service, document_id: str):
    """Lê o documento, consulta o Gemini e formata o layout."""
    print("\n[AGENTE ABNT] Lendo documento...")
    doc = docs_service.documents().get(documentId=document_id).execute()
    
    texto_plano = ""
    for item in doc.get('body').get('content', []):
        if 'paragraph' in item:
            for element in item.get('paragraph').get('elements', []):
                if 'textRun' in element:
                    texto_plano += element.get('textRun').get('content')

    if texto_plano.strip():
        print("[AGENTE ABNT] Analisando citações e referências com o Gemini...")
        texto_revisado = revisar_texto_com_gemini(texto_plano)
        print("[AGENTE ABNT] Texto analisado e revisado pela IA!")

    print("[AGENTE ABNT] Ajustando margens, fonte e recuos...")
    aplicar_formatacao_abnt_docs(docs_service, document_id)


def monitorar_documento(document_id: str, intervalo_segundos: int = 10):
    """Monitora alterações no documento via API do Google Drive."""
    docs_service, drive_service = autenticar_google_workspace()
    
    print(f"=== Monitoramento Iniciado ===")
    print(f"Acompanhando alterações no documento ID: {document_id}")
    print("Pressione Ctrl+C para encerrar.\n")

    ultima_modificacao = None

    try:
        while True:
            file_metadata = drive_service.files().get(
                fileId=document_id, 
                fields='modifiedTime'
            ).execute()
            
            modificacao_atual = file_metadata.get('modifiedTime')

            if ultima_modificacao is None:
                ultima_modificacao = modificacao_atual
                print("Executando a primeira formatação...")
                executar_agente_abnt(docs_service, document_id)
            elif modificacao_atual != ultima_modificacao:
                print(f"\n[ALERTA] Alteração detectada! Data/Hora: {modificacao_atual}")
                ultima_modificacao = modificacao_atual
                executar_agente_abnt(docs_service, document_id)

            time.sleep(intervalo_segundos)
    except KeyboardInterrupt:
        print("\nMonitoramento encerrado pelo usuário.")


if __name__ == "__main__":
    # Cole aqui o ID do seu Google Docs (encontrado na URL do seu documento)
    # Exemplo: https://docs.google.com/document/d/SEU_ID_AQUI/edit
    DOCUMENT_ID = "ID_SEU_DOCUMENTO"
    
    monitorar_documento(DOCUMENT_ID, intervalo_segundos=10)