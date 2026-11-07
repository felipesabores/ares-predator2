"""
DB Writer - Salva DataFrames do Pandas no PostgreSQL.
Tabela emissoes: upsert por id_minuta.
Demais tabelas: truncate + insert (JSONB por linha).
"""

import json
import math
import logging
import psycopg2
import pandas as pd
from psycopg2.extras import execute_values

log = logging.getLogger(__name__)

from src.settings import db_config

REPORT_MAP = {
    "106":  {"table": "emissoes",        "key_col": "MINUTA"},
    # 106f = variante full do 106 (sem SEM RECEBEDOR) usada pra fat_dia/fat_ontem.
    # UPSERT por MINUTA — preserva histórico quando janela do scraper < cobertura total.
    "106f": {"table": "emissoes_dia",    "key_col": "MINUTA", "upsert_only": True},
    "138":  {"table": "coletas",         "key_col": None},
    "027":  {"table": "cotacoes",        "key_col": None},
    "399":  {"table": "remessas",        "key_col": None},
    "129":  {"table": "awbs",            "key_col": None},
    "295":  {"table": "canhotos",        "key_col": None},
    "314":  {"table": "pereciveis",      "key_col": None},
    "147":  {"table": "custos_operacao", "key_col": None},
}


def get_db():
    conn = psycopg2.connect(**db_config(), connect_timeout=10)
    conn.cursor().execute("SET statement_timeout = '30s'")
    conn.cursor().execute("SET lock_timeout = '10s'")
    conn.commit()
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Migração: se emissoes existe sem coluna 'dados', recria com novo schema
    cur.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='emissoes')
            AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='emissoes' AND column_name='dados'
            ) THEN
                DROP TABLE emissoes;
            END IF;
        END $$;
    """)

    # emissoes: upsert por id_minuta
    cur.execute("""
        CREATE TABLE IF NOT EXISTS emissoes (
            id_minuta TEXT PRIMARY KEY,
            dados     JSONB NOT NULL,
            sync_em   TIMESTAMP DEFAULT NOW()
        )
    """)

    # demais relatórios: JSONB por linha, truncate+insert a cada sync
    for table in ("coletas", "cotacoes", "remessas", "awbs", "canhotos", "pereciveis", "custos_operacao", "emissoes_dia"):
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id      SERIAL PRIMARY KEY,
                dados   JSONB NOT NULL,
                sync_em TIMESTAMP DEFAULT NOW()
            )
        """)
        # Migração sync_em removida — coluna já existe em todas as tabelas desde 2026-06.
        # O ALTER TABLE segurava lock exclusivo e causava cascata de locks a cada sync.

    # Migrar emissoes_dia para UPSERT por MINUTA (antes era TRUNCATE+INSERT).
    # Adiciona coluna id_minuta + unique constraint se não existem.
    cur.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'emissoes_dia' AND column_name = 'id_minuta'
            ) THEN
                ALTER TABLE emissoes_dia ADD COLUMN id_minuta TEXT;
                UPDATE emissoes_dia SET id_minuta = dados->>'MINUTA';
                CREATE UNIQUE INDEX IF NOT EXISTS uq_emissoes_dia_minuta ON emissoes_dia (id_minuta);
            END IF;
        END $$;
    """)

    # Índice para lookup rápido de tabela comercial (CV) em emissoes_dia
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_emissoes_dia_minuta
        ON emissoes_dia ((dados->>'MINUTA'))
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_log (
            id          SERIAL PRIMARY KEY,
            relatorio   VARCHAR(50),
            registros   INTEGER,
            status      VARCHAR(20),
            erro        TEXT,
            executado_em TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.commit()
    cur.close()
    conn.close()
    log.info("Banco inicializado.")


def _nan_to_none(v):
    """Convert float NaN/Inf to None so JSON serialization is valid."""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v

def _row_to_json(row):
    d = {k: _nan_to_none(v) for k, v in row.to_dict().items()}
    return json.dumps(d, ensure_ascii=False, default=str)


def _normalize_emissoes(df):
    """Normaliza 'Embarque Completo' (130+ colunas) para o schema esperado pelas APIs."""
    if df is None or df.empty or 'MINUTA' in df.columns:
        return df  # já está no formato antigo

    def to_centavos(series):
        return (pd.to_numeric(series, errors='coerce').fillna(0) * 100).round().astype(int).astype(str)

    if 'MD' in df.columns:
        df = df.rename(columns={'MD': 'MINUTA'})

    if 'EMISSAO' in df.columns and 'DATA' not in df.columns:
        df['DATA'] = pd.to_datetime(df['EMISSAO'], errors='coerce').dt.strftime('%d/%m/%Y')

    frete = pd.to_numeric(df.get('FRETE TOTAL', pd.Series(dtype=float)), errors='coerce').fillna(0)
    icms  = pd.to_numeric(df.get('VALOR ICMS',  pd.Series(dtype=float)), errors='coerce').fillna(0)
    df['TOTAL COBRADO'] = ((frete + icms) * 100).round().astype(int).astype(str)
    df['FRETE S/ICMS']  = (frete * 100).round().astype(int).astype(str)
    df['ICMS']          = (icms  * 100).round().astype(int).astype(str)

    for src, dst in [('FRETE PESO','FRETE PESO'), ('TX. ADV','AD VALOREM'),
                     ('TX. DESPACHO','REDESPACHO'), ('TX. COLETA','EXC. COLETA'),
                     ('TX. ENTREGA','EXC. ENTREGA')]:
        if src in df.columns:
            df[dst] = to_centavos(df[src])

    if 'UF.2' in df.columns:
        df['UF.1'] = df['UF.2']  # UF.2 = UF destino (equivalente ao UF.1 do formato antigo)
    if 'SERVICO' in df.columns and 'SERVIÇO' not in df.columns:
        df['SERVIÇO'] = df['SERVICO']
    if 'NF VALOR' in df.columns and 'VALOR NF' not in df.columns:
        df['VALOR NF'] = to_centavos(df['NF VALOR'])
    if 'PESO REAL' in df.columns and 'PESO' not in df.columns:
        df['PESO'] = df['PESO REAL'].astype(str)

    log.info(f"[emissoes] Embarque Completo normalizado: {len(df)} registros")
    return df


def save_emissoes(df):
    """Upsert por MINUTA (chave primária do relatório 106).
    Filtra registros com DATA anterior a 01/01/2025 antes de salvar.
    """
    if df is None or df.empty:
        return 0

    df = _normalize_emissoes(df)

    # Filtrar apenas emissões a partir de 01/01/2025
    if "DATA" in df.columns:
        before = len(df)
        df["_data_parsed"] = pd.to_datetime(df["DATA"], format="%d/%m/%Y", errors="coerce")
        df = df[df["_data_parsed"] >= pd.Timestamp("2025-01-01")].drop(columns=["_data_parsed"])
        after = len(df)
        log.info(f"[emissoes] filtro de data: {before} -> {after} registros (removidos {before - after} anteriores a 2025)")
    if df.empty:
        return 0

    key_col = "MINUTA"
    if key_col not in df.columns:
        raise ValueError(f"Coluna '{key_col}' não encontrada no DataFrame de emissoes.")

    # Guard rail: rejeita XLSX que não seja o Excel rico (149 cols). Sem TIPO EMISSAO
    # o Portal Cliente perde devoluções e o filtro de Tipo Emissão fica quebrado.
    required = ("TIPO EMISSAO", "COMPROVANTE ENTREGA")
    missing = [c for c in required if c not in df.columns]
    if missing:
        cols_preview = ", ".join(list(df.columns)[:25])
        raise ValueError(
            f"[emissoes] GUARD RAIL: XLSX sem colunas {missing} — provavelmente Embarque Completo "
            f"enxuto (40 cols). NÃO será salvo. df.columns (primeiras 25): {cols_preview}"
        )

    rows = [
        (str(row[key_col]), _row_to_json(row))
        for _, row in df.iterrows()
        if str(row.get(key_col, "")).strip() not in ("", "nan")
    ]
    if not rows:
        return 0

    minutas_atuais = [r[0] for r in rows]

    conn = get_db()
    cur = conn.cursor()
    try:
        execute_values(cur, """
            INSERT INTO emissoes (id_minuta, dados, sync_em)
            VALUES %s
            ON CONFLICT (id_minuta) DO UPDATE
                SET dados   = EXCLUDED.dados,
                    sync_em = NOW()
        """, [(r[0], r[1]) for r in rows],
        template="(%s, %s::jsonb, NOW())")

        # Remove notas que saíram do relatório (foram entregues)
        cur.execute("""
            DELETE FROM emissoes
            WHERE id_minuta <> ALL(%s)
        """, (minutas_atuais,))
        deletados = cur.rowcount
        if deletados:
            log.info(f"[emissoes] {deletados} notas removidas (entregues/fora do relatório)")

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

    return len(rows)


def save_generic(table, df):
    """Truncate + insert JSONB para relatórios sem chave primária natural."""
    if df is None or df.empty:
        return 0

    rows = [(_row_to_json(row),) for _, row in df.iterrows()]

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(f"TRUNCATE TABLE {table}")
        execute_values(cur,
            f"INSERT INTO {table} (dados, sync_em) VALUES %s",
            rows,
            template="(%s::jsonb, NOW())"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

    return len(rows)


def save_emissoes_dia(df):
    """UPSERT por MINUTA na tabela emissoes_dia.
    Diferente de save_emissoes: NÃO deleta minutas ausentes do relatório,
    porque a janela do scraper pode ser menor que a cobertura total.
    """
    if df is None or df.empty:
        return 0

    df = _normalize_emissoes(df)

    key_col = "MINUTA"
    if key_col not in df.columns:
        raise ValueError(f"Coluna '{key_col}' não encontrada no DataFrame de emissoes_dia.")

    rows = [
        (str(row[key_col]), _row_to_json(row))
        for _, row in df.iterrows()
        if str(row.get(key_col, "")).strip() not in ("", "nan")
    ]
    if not rows:
        return 0

    conn = get_db()
    cur = conn.cursor()
    try:
        execute_values(cur, """
            INSERT INTO emissoes_dia (id_minuta, dados, sync_em)
            VALUES %s
            ON CONFLICT (id_minuta) DO UPDATE
                SET dados   = EXCLUDED.dados,
                    sync_em = NOW()
        """, [(r[0], r[1]) for r in rows],
        template="(%s, %s::jsonb, NOW())")

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

    return len(rows)


def save_dataframe(report_id, df):
    """Entry point: decide estratégia por report_id."""
    cfg = REPORT_MAP.get(report_id)
    if not cfg:
        raise ValueError(f"report_id desconhecido: {report_id}")

    table   = cfg["table"]
    key_col = cfg["key_col"]

    if report_id == "106f":
        return save_emissoes_dia(df)
    if key_col:
        return save_emissoes(df)
    return save_generic(table, df)


def log_sync(relatorio, registros, status, erro=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sync_log (relatorio, registros, status, erro)
        VALUES (%s, %s, %s, %s)
    """, (relatorio, registros, status, erro))
    conn.commit()
    cur.close()
    conn.close()
