"""
Backfill one-shot do relatório 147 (Custo por Operação) em chunks.

O Brudam parece ter limite de janela no 147 — janelas grandes (17 meses)
voltam vazias. Esse script quebra em chunks de 3 meses e acumula o
resultado em `custos_operacao_historico`.

Tabela alvo SEPARADA: não toca em `custos_operacao` (gerenciada pelo
sync diário). A API /api/comercial faz UNION das duas pra ter histórico
completo no gráfico Comparativo.

Como rodar:
    python backfill_147.py

Pre-requisitos:
    - Estar no Brasil (geo-bloqueio do Brudam)
    - Playwright instalado (chromium)
    - psycopg2 + pandas + html5lib instalados
"""

import os
import sys
import glob
import logging
import argparse
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

from psycopg2.extras import execute_values

from src.services.report_fetcher import BrudamRobot
from src.utils.data_processor import process_report_upload
from src.db.writer import get_db, _row_to_json
from src.settings import brudam_credentials

# ─── Configuração ─────────────────────────────────────────────
DOWNLOAD_PATH = "data/raw"
TARGET_TABLE  = "custos_operacao_historico"

# Tamanho mínimo do XLSX (bytes) pra considerar resposta válida.
# Resposta vazia do Brudam costuma ser ~250 bytes (só CSS).
MIN_FILE_SIZE = 1000


def _parse_args():
    p = argparse.ArgumentParser(description="Backfill/refresh do relatório 147")
    p.add_argument(
        "--dias", type=int, default=None,
        help="Modo recente: baixa só os últimos N dias (ex: --dias 35). "
             "Sem este flag roda o backfill completo desde 01/01/2025.",
    )
    return p.parse_args()


def _resolve_window(dias):
    now = datetime.now()
    if dias is not None:
        # Refresh da janela rolante: últimos N dias → hoje
        start = (now - timedelta(days=dias)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now, 1  # chunks mensais — janelas > 30d são rejeitadas pelo Brudam
    else:
        # Backfill completo: jan/2025 → hoje em chunks mensais
        return datetime(2025, 1, 1), now, 1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("backfill_147")


def get_latest_147_file():
    pattern = os.path.join(DOWNLOAD_PATH, "report_147_*.xlsx")
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None


def clear_147_files():
    """Remove XLSXs antigos do 147 antes de cada chunk."""
    for f in glob.glob(os.path.join(DOWNLOAD_PATH, "report_147_*.xlsx")):
        os.remove(f)


def ensure_table():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {TARGET_TABLE} (
            id      SERIAL PRIMARY KEY,
            dados   JSONB NOT NULL,
            sync_em TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{TARGET_TABLE}_data ON {TARGET_TABLE} ((dados->>'DATA'))")
    # Índice ÚNICO na MINUTA: chave natural do 147 (1 minuta = 1 linha, nunca
    # repete entre meses — verificado). É o que torna o upsert idempotente e
    # elimina a necessidade de TRUNCATE. NÃO remover.
    cur.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{TARGET_TABLE}_minuta ON {TARGET_TABLE} ((dados->>'MINUTA'))")
    conn.commit()
    cur.close()
    conn.close()


def upsert_historico(df):
    """UPSERT por MINUTA — idempotente. Rodar 2x não duplica: minuta que já
    existe tem os dados atualizados (útil pro mês em aberto, cujos custos ainda
    mudam no Brudam); minuta nova é inserida. SEM TRUNCATE, SEM DELETE — o
    histórico de meses fechados nunca é destruído por uma re-execução."""
    if df is None or df.empty:
        return 0

    rows = [(_row_to_json(row),) for _, row in df.iterrows()]

    conn = get_db()
    cur = conn.cursor()
    try:
        execute_values(
            cur,
            f"""INSERT INTO {TARGET_TABLE} (dados, sync_em) VALUES %s
                ON CONFLICT ((dados->>'MINUTA')) DO UPDATE
                SET dados = EXCLUDED.dados, sync_em = NOW()""",
            rows,
            template="(%s::jsonb, NOW())",
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return len(rows)


def build_chunks(start: datetime, end: datetime, months: int):
    """Gera lista de (start, end) cobrindo o range, em chunks fechados de N meses."""
    chunks = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + relativedelta(months=months) - timedelta(days=1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def run_chunk(start: datetime, end: datetime) -> int:
    """Roda 1 chunk e retorna o número de registros inseridos."""
    start_str = start.strftime("%d/%m/%Y")
    end_str   = end.strftime("%d/%m/%Y")
    log.info(f"[CHUNK] {start_str} → {end_str}")

    clear_147_files()

    # O scraper hardcoda end_date = hoje. Como queremos chunks fechados,
    # passamos end_date via env var lida no fetch (workaround: monkey-patch).
    # Atalho mais simples: passar via start_date_override sintaticamente
    # não funciona (só tem start). Precisamos do end também.
    #
    # Solução: o scraper só tem 1 hook (start_date_override). Pra controlar
    # o end_date, vamos monkey-patchar datetime.now() do módulo do scraper.
    # Mais limpo seria adicionar end_date_override, mas pra um one-shot vai.
    import src.services.report_fetcher as rf
    original_datetime = rf.datetime

    class FixedDatetime(original_datetime):
        @classmethod
        def now(cls, tz=None):
            return end  # força end_date a ser nosso chunk end

    rf.datetime = FixedDatetime

    try:
        robot = BrudamRobot(
            download_path=DOWNLOAD_PATH,
            only_reports=["147"],
            start_date_override={"147": start_str},
        )
        robot.fetch_all_reports(*brudam_credentials())
    finally:
        rf.datetime = original_datetime

    filepath = get_latest_147_file()
    if not filepath:
        log.warning(f"[CHUNK {start_str}-{end_str}] Nenhum XLSX baixado.")
        return 0

    size = os.path.getsize(filepath)
    if size < MIN_FILE_SIZE:
        log.warning(f"[CHUNK {start_str}-{end_str}] XLSX vazio ({size} bytes) — Brudam recusou ou não há dados.")
        return 0

    log.info(f"[CHUNK {start_str}-{end_str}] XLSX: {size/1024:.1f} KB")

    try:
        df = process_report_upload(filepath)
    except Exception as e:
        log.error(f"[CHUNK {start_str}-{end_str}] Falha no parse: {e}")
        return 0

    count = upsert_historico(df)
    log.info(f"[CHUNK {start_str}-{end_str}] {count} registros (upsert por MINUTA)")
    return count


def run(window_start: datetime, window_end: datetime, chunk_months: int, modo: str):
    log.info("=" * 60)
    log.info(f"Backfill 147 [{modo}] iniciado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log.info(f"Janela: {window_start.strftime('%d/%m/%Y')} → {window_end.strftime('%d/%m/%Y')}")
    log.info(f"Chunks de {chunk_months} meses | Tabela: {TARGET_TABLE}")

    ensure_table()
    log.info("Modo UPSERT por MINUTA (sem truncate) — re-execução é idempotente.")

    chunks = build_chunks(window_start, window_end, chunk_months)
    log.info(f"Total de chunks: {len(chunks)}")
    for i, (s, e) in enumerate(chunks, 1):
        log.info(f"  {i}/{len(chunks)}: {s.strftime('%d/%m/%Y')} → {e.strftime('%d/%m/%Y')}")

    total = 0
    falhados = []
    for i, (s, e) in enumerate(chunks, 1):
        log.info(f"--- Chunk {i}/{len(chunks)} ---")
        try:
            count = run_chunk(s, e)
            total += count
            if count == 0:
                falhados.append((s, e))
        except Exception as ex:
            log.error(f"[CHUNK {i}] ERRO fatal: {ex}")
            falhados.append((s, e))

    log.info("=" * 60)
    log.info(f"CONCLUÍDO [{modo}]: {total} registros em {TARGET_TABLE}")
    if falhados:
        log.warning(f"Chunks sem dados/falhos ({len(falhados)}):")
        for s, e in falhados:
            log.warning(f"  - {s.strftime('%d/%m/%Y')} → {e.strftime('%d/%m/%Y')}")
    log.info(f"Fim: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log.info("=" * 60)


if __name__ == "__main__":
    args = _parse_args()
    window_start, window_end, chunk_months = _resolve_window(args.dias)
    modo = f"recente {args.dias}d" if args.dias else "completo"
    run(window_start, window_end, chunk_months, modo)
