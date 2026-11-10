import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive'
]

def autenticar_google_workspace():
    # Encontra a pasta RAIZ do projeto subindo 2 níveis a partir de src/agente_abnt/
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
    
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
                print(f"[AUTENTICAÇÃO] Renovação falhou ({e}). Reautenticando...")
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