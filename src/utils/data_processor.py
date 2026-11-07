import pandas as pd

def process_report_upload(uploaded_file):
    """
    Reads the uploaded file and standardizes it.
    """
    # Determine filename/extension
    if isinstance(uploaded_file, str):
        filename = uploaded_file
    else:
        filename = uploaded_file.name
        
    if filename.lower().endswith('.csv'):
        df = pd.read_csv(uploaded_file, sep=';', encoding='latin1', on_bad_lines='skip')
    else:
        try:
            # Try reading as true Excel
            df = pd.read_excel(uploaded_file, engine='openpyxl')
        except Exception:
            # Fallback: It might be an HTML table saved as .xlsx (common in legacy systems)
            # read_html returns a list of DataFrames
            # We need to reset the file pointer if it's a file-like object
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)
            
            dfs = pd.read_html(uploaded_file, encoding='utf-8', header=0)
            if dfs:
                # heuristic: prefer table with most rows and columns, 
                # but specifically look for real data signatures
                best_df = None
                max_score = -1
                
                for d in dfs:
                    score = d.shape[0] * d.shape[1]
                    # penalty for "filter" tables (usually 1 row)
                    if d.shape[0] <= 1: score = 0
                    
                    if score > max_score:
                        max_score = score
                        best_df = d
                
                df = best_df if best_df is not None else dfs[0]
            else:
                raise ValueError("No tables found in the HTML-based Excel file.")
    
    # Basic cleanup
    df.columns = df.columns.str.strip() # Remove spaces, keep original case for mapping
    
    # --- REPORT SPECIFIC CORRECTIONS ---
    # Report 027 (Cotações) - Header mapping
    if 'Valor R$' in df.columns:
        df.rename(columns={'Valor R$': 'Valor'}, inplace=True)
    if 'CLIENTE COM FANTASIA PARECIDA' in df.columns:
        df.rename(columns={'CLIENTE COM FANTASIA PARECIDA': 'CLIENTE'}, inplace=True)
    if 'DATA EMISSÃO (DE - ATÉ)' in df.columns:
        df.rename(columns={'DATA EMISSÃO (DE - ATÉ)': 'DATA_EMISSAO'}, inplace=True)
    if 'Data Emissão' in df.columns:
        df.rename(columns={'Data Emissão': 'DATA_EMISSAO'}, inplace=True)
        
    # Report 399 (Remessas) - Header mapping
    if 'OCORRENCIA' in df.columns:
        df.rename(columns={'OCORRENCIA': 'Status'}, inplace=True)
    if 'CIDADE.1' in df.columns:
        df.rename(columns={'CIDADE.1': 'Destino'}, inplace=True)
    if 'NF VALOR' in df.columns:
        df.rename(columns={'NF VALOR': 'Valor'}, inplace=True)

    # Report 129 (AWBs) - Header mapping
    if 'ULTIMO STATUS' in df.columns:
        df.rename(columns={'ULTIMO STATUS': 'Status'}, inplace=True)
    if 'CIA - DESPACHO' in df.columns:
        df.rename(columns={'CIA - DESPACHO': 'Companhia'}, inplace=True)
    if 'CIDADE.1' in df.columns:
        # Note: If 399 also has CIDADE.1 it is handled above, but if 129 has it differently it's fine
        # because the rename is idempotent if already renamed.
        df.rename(columns={'CIDADE.1': 'Destino'}, inplace=True)

    # Standardize to UPPERCASE for internal matching
    df.columns = df.columns.str.upper()

    # --- Report 147 (Custos por Operação) — filtro de totalizador ---
    # O XLSX do 147 traz 3 tipos de linhas que NÃO são detalhes reais:
    #   1. Subtítulo "Cliente: NOME" — MINUTA = "Cliente: ..." (string)
    #   2. Subtotal por cliente     — MINUTA = <int pequeno> (count de CT-Es),
    #                                 mas DATA/CT-E/etc. = NaN
    #   3. Totalizador geral        — duas linhas no final: uma com
    #                                 MINUTA="TOTAL" (re-header), outra com o
    #                                 count total e os valores somados
    # Heurística mestre: detalhe real SEMPRE tem MINUTA numérica (≥6 dígitos,
    # é o ID do CT-E) E DATA em formato DD/MM/YYYY. Qualquer linha que não
    # bata os dois critérios é lixo.
    #
    # Identificamos o relatório 147 pela presença simultânea das colunas
    # 'LUCRO LIQ', 'MINUTA' e 'DATA' (assinatura única — outros relatórios
    # não têm essa combinação).
    if {'LUCRO LIQ', 'MINUTA', 'DATA'}.issubset(df.columns):
        before = len(df)
        # MINUTA precisa ser inteira (≥6 dígitos pra evitar contagens 1..N
        # que aparecem em subtotais por cliente)
        minuta_str = df['MINUTA'].astype(str).str.strip()
        valid_minuta = minuta_str.str.match(r'^\d{6,}$', na=False)
        # DATA precisa ser DD/MM/YYYY
        data_str = df['DATA'].astype(str).str.strip()
        valid_data = data_str.str.match(r'^\d{2}/\d{2}/\d{4}$', na=False)
        df = df[valid_minuta & valid_data].copy()
        dropped = before - len(df)
        if dropped > 0:
            import logging
            logging.getLogger(__name__).info(
                f"[147] Filtro de totalizador: descartadas {dropped} linhas "
                f"(subtítulos/subtotais/totalizador), restam {len(df)}"
            )

    return df

def merge_api_data(report_df, api_data):
    """
    Merges the original report with data fetched from API.
    """
    return report_df

def clean_currency_column(series):
    """
    Cleans R$ currency strings to float.
    Example: 'R$ 1.234,56' -> 1234.56
    """
    if series.dtype == 'float64' or series.dtype == 'int64':
        return series
        
    return series.astype(str).str.replace('R$', '', regex=False)\
                             .str.replace('.', '', regex=False)\
                             .str.replace(',', '.', regex=False)\
                             .str.strip()\
                             .astype(float)
