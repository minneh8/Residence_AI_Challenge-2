def renderizar_layout_abnt_no_docs(docs_service, document_id: str, artigo: dict):
    """Atualiza o conteúdo no Google Docs sem duplicar títulos e garantindo numeração inicial no 1."""
    print("[AGENTE ABNT] Reconstruindo texto no Google Docs...")
    
    doc = docs_service.documents().get(documentId=document_id).execute()
    body_content = doc.get('body', {}).get('content', [])
    end_index = body_content[-1].get('endIndex', 1) - 1

    requests = []

    # 1. Limpa o texto antigo do documento
    if end_index > 1:
        requests.append({
            'deleteContentRange': {
                'range': {'startIndex': 1, 'endIndex': end_index}
            }
        })

    # 2. Extrai os dados do JSON
    titulo = artigo.get("titulo_principal", "").strip().upper()
    autores = artigo.get("autores", "").strip()
    resumo = artigo.get("resumo", "").strip()
    palavras_chave = artigo.get("palavras_chave", "").strip()
    elementos = artigo.get("elementos", [])

    # Monta o cabeçalho inicial único (Título Principal e Autores)
    texto_gerado = f"{titulo}\n"
    if autores:
        texto_gerado += f"{autores}\n\n"
    else:
        texto_gerado += "\n"

    if resumo:
        texto_gerado += f"RESUMO\n{resumo}\n"
        if palavras_chave:
            texto_gerado += f"{palavras_chave}\n\n"

    titulos_para_negrito = set()
    if resumo:
        titulos_para_negrito.add("RESUMO")

    contador_ref = 1

    # Montagem dos elementos sem duplicações
    for el in elementos:
        tipo = el.get("tipo", "PARAGRAFO")
        num = el.get("numeracao")
        txt = el.get("texto", "").strip()

        if not txt:
            continue

        # --- FILTROS DE PREVENÇÃO CONTRA DUPLICAÇÃO ---
        # Descarta se for uma repetição do título principal
        if txt.upper() == titulo.upper():
            continue
        # Descarta se for repetição do nome do autor
        if autores and txt.lower() in autores.lower():
            continue
        # Descarta se for repetição do resumo ou palavras-chave
        if "resumo" in txt.lower() and (num in ["1.", "1"] or not num) and resumo:
            continue
        if txt.startswith("PALAVRAS-CHAVE") and palavras_chave:
            continue

        # Processamento das seções
        if tipo in ["TITULO_SECAO", "SUBTITULO_SECAO"]:
            txt_upper = txt.upper()
            if num and not txt_upper.startswith(str(num)):
                linha_titulo = f"{num} {txt_upper}"
            else:
                linha_titulo = txt_upper
            texto_gerado += f"{linha_titulo}\n"
            titulos_para_negrito.add(linha_titulo.strip())

        elif tipo == "REFERENCIA":
            if num and not txt.startswith("["):
                texto_gerado += f"{num} {txt}\n"
            elif txt.startswith("["):
                texto_gerado += f"{txt}\n"
            else:
                texto_gerado += f"[{contador_ref}] {txt}\n"
                contador_ref += 1
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

    # 3. Estilização Visual ABNT
    print("[AGENTE ABNT] Aplicando estilos visuais ABNT...")
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

        p_text = "".join([
            el.get('textRun', {}).get('content', '') 
            for el in item.get('paragraph', {}).get('elements', []) 
            if 'textRun' in el
        ]).strip()

        if not p_text:
            continue

        # A. TÍTULO PRINCIPAL (14pt, Negrito, Centralizado)
        if p_text == titulo:
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

        # B. AUTORES (11pt, Itálico, Centralizado abaixo do título)
        elif p_text == autores:
            style_requests.append({
                'updateTextStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'textStyle': {'weightedFontFamily': {'fontFamily': 'Arial'}, 'fontSize': {'magnitude': 11, 'unit': 'PT'}, 'italic': True, 'bold': False},
                    'fields': 'weightedFontFamily,fontSize,italic,bold'
                }
            })
            style_requests.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': start_index, 'endIndex': end_index},
                    'paragraphStyle': {'alignment': 'CENTER', 'lineSpacing': 150, 'spaceBelow': {'magnitude': 18, 'unit': 'PT'}},
                    'fields': 'alignment,lineSpacing,spaceBelow'
                }
            })

        # C. PALAVRAS-CHAVE
        elif p_text.startswith("PALAVRAS-CHAVE"):
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

        # D. TÍTULOS DE SEÇÃO (12pt, Negrito, Caixa Alta)
        elif p_text in titulos_para_negrito or (p_text[0].isdigit() and "." in p_text[:4]) or p_text.startswith("REFERÊNCIAS"):
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

        # E. REFERÊNCIAS BIBLIOGRÁFICAS (11pt, Alinhado à Esquerda)
        elif p_text.startswith("["):
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

        # F. PARÁGRAFO DO CORPO (12pt, Justificado, Recuo 1,25cm)
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
        print(" -> [SUCESSO] Documento formatado!")