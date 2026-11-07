"""
ARES Sync - Orquestrador principal.
1. Roda o robô Playwright para baixar os 6 relatórios como XLSX.
2. Processa cada XLSX com Pandas.
3. Faz upsert/insert no PostgreSQL da VPS.

Agendar via Windows Task Scheduler a cada 30 minutos.
"""

import os
import glob
import logging
from datetime import datetime

from src.settings import brudam_credentials
from src.services.report_fetcher import BrudamRobot
from src.utils.data_processor import process_report_upload
from src.db.writer import init_db, save_dataframe, log_sync, REPORT_MAP

# ─── Configuração ─────────────────────────────────────────────
DOWNLOAD_PATH = "data/raw"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("sync.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────
def get_latest_file(report_id: str):
    """Retorna o XLSX mais recente para um dado report_id."""
    pattern = os.path.join(DOWNLOAD_PATH, f"report_{report_id}_*.xlsx")
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


# ─── Main ─────────────────────────────────────────────────────
def run():
    log.info("=" * 55)
    log.info(f"ARES Sync iniciado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

    # 1. Inicializa banco
    init_db()

    # 2. Roda robô
    log.info("Iniciando robô Brudam...")
    robot = BrudamRobot(download_path=DOWNLOAD_PATH)
    robot.fetch_all_reports(*brudam_credentials())
    log.info("Robô finalizado.")

    # 3. Processa e salva cada relatório
    for report_id, cfg in REPORT_MAP.items():
        table = cfg["table"]

        filepath = get_latest_file(report_id)
        if not filepath:
            log.warning(f"[{report_id}] Nenhum arquivo em {DOWNLOAD_PATH} — pulando.")
            log_sync(table, 0, "erro", "Arquivo não encontrado")
            continue

        log.info(f"[{report_id}] Processando: {os.path.basename(filepath)}")
        try:
            df = process_report_upload(filepath)
            count = save_dataframe(report_id, df)
            log.info(f"[{report_id}] -> {table}: {count} registros salvos")
            log_sync(table, count, "ok")
            # Apaga todos os XLSXs deste relatório após salvar com sucesso
            for f in glob.glob(os.path.join(DOWNLOAD_PATH, f"report_{report_id}_*.xlsx")):
                os.remove(f)
                log.info(f"[{report_id}] Arquivo removido: {os.path.basename(f)}")
        except Exception as e:
            log.error(f"[{report_id}] ERRO: {e}")
            log_sync(table, 0, "erro", str(e))

    log.info(f"Sync concluído: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log.info("=" * 55)


if __name__ == "__main__":
    run()
