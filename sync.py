"""
ARES Sync - Orquestrador principal.

1. Lê no banco quais relatórios estão vencidos (painel Predator do ares-web2).
2. Roda o robô Playwright só para esses relatórios.
3. Processa cada XLSX com Pandas e grava no PostgreSQL.
4. Registra cada execução em predator_execucoes (e no sync_log legado).

Feito para rodar pelo cron A CADA MINUTO: quando nada está vencido, sai em
menos de 1 segundo sem abrir o navegador. O intervalo de cada relatório é
definido no painel, não no cron.

Se as tabelas predator_* ainda não existirem, roda no modo antigo (todos os
relatórios a cada chamada).

Códigos de saída (usados pelo run-sync.sh para decidir se notifica):
  0  rodou e tudo deu certo
  1  rodou e algum relatório falhou
  75 nada a fazer (nada vencido ou outro sync em andamento)
"""

import fcntl
import glob
import logging
import os
import sys
from datetime import datetime

from src.settings import brudam_credentials
from src.services.report_fetcher import BrudamRobot
from src.utils.data_processor import process_report_upload
from src.db.writer import init_db, save_dataframe, log_sync, REPORT_MAP
from src.control import JobControl, Job

# ─── Configuração ─────────────────────────────────────────────
DOWNLOAD_PATH = "data/raw"
LOCK_FILE     = "data/sync.lock"
EXIT_NOTHING  = 75

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


def acquire_lock():
    """Garante um sync por vez na máquina. Retorna o handle ou None se ocupado."""
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    fh = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except BlockingIOError:
        fh.close()
        return None


def plan(control):
    """Lista de jobs a rodar agora. None = modo antigo (todos os relatórios)."""
    if control is None or not control.available():
        return None
    control.cleanup_stale()
    due = control.due_jobs()
    for j in due:
        if j.report_id not in REPORT_MAP and control.start(j):
            control.finish(j, "erro", erro=f"Sem implementação para o job '{j.id}' no predator")
    return [j for j in due if j.report_id in REPORT_MAP]


def process_report(report_id: str):
    """Processa o XLSX baixado de um relatório. Retorna (status, registros, erro)."""
    table = REPORT_MAP[report_id]["table"]
    filepath = get_latest_file(report_id)
    if not filepath:
        log.warning(f"[{report_id}] Nenhum arquivo em {DOWNLOAD_PATH} — pulando.")
        log_sync(table, 0, "erro", "Arquivo não encontrado")
        return "erro", 0, "Arquivo não encontrado (download do Brudam falhou)"

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
        return "ok", count, None
    except Exception as e:
        log.error(f"[{report_id}] ERRO: {e}")
        log_sync(table, 0, "erro", str(e))
        return "erro", 0, str(e)


# ─── Main ─────────────────────────────────────────────────────
def run() -> int:
    lock = acquire_lock()
    if lock is None:
        log.info("Outro sync ainda está rodando — saindo.")
        return EXIT_NOTHING

    control = None
    jobs: list[Job] | None = None
    try:
        try:
            control = JobControl()
        except Exception as e:
            log.error(f"[control] Sem conexão para ler o painel: {e}")
            control = None

        jobs = plan(control)
        if jobs is not None and not jobs:
            return EXIT_NOTHING  # nada vencido: sai sem abrir o navegador

        log.info("=" * 55)
        log.info(f"ARES Sync iniciado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

        if jobs is None:
            log.info("Modo antigo: painel Predator indisponível, rodando todos os relatórios.")
            report_ids = list(REPORT_MAP.keys())
        else:
            jobs = [j for j in jobs if control.start(j)]
            if not jobs:
                return EXIT_NOTHING
            report_ids = [j.report_id for j in jobs]
            log.info("Relatórios desta rodada: " + ", ".join(
                f"{j.report_id}{' (manual)' if j.origem == 'manual' else ''}" for j in jobs))

        init_db()

        # Robô baixa os XLSX; se ele cair, cada relatório sem arquivo vira erro abaixo.
        robot_error = None
        try:
            robot = BrudamRobot(download_path=DOWNLOAD_PATH, only_reports=report_ids)
            robot.fetch_all_reports(*brudam_credentials())
            log.info("Robô finalizado.")
        except Exception as e:
            robot_error = f"Robô falhou: {e}"
            log.error(robot_error)

        by_report = {j.report_id: j for j in (jobs or [])}
        failures = 0
        for report_id in report_ids:
            status, count, erro = process_report(report_id)
            if status != "ok":
                failures += 1
                if robot_error and erro and erro.startswith("Arquivo não encontrado"):
                    erro = robot_error
            job = by_report.get(report_id)
            if job and control:
                control.finish(job, status, registros=count if status == "ok" else None, erro=erro)

        log.info(f"Sync concluído: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        log.info("=" * 55)
        return 1 if failures else 0

    finally:
        # Qualquer execução que ficou aberta (exceção inesperada) é fechada como erro.
        if control:
            for job in jobs or []:
                if job.exec_id is not None:
                    try:
                        control.finish(job, "erro", erro="Sync interrompido por exceção inesperada")
                    except Exception:
                        pass
            control.close()
        lock.close()


if __name__ == "__main__":
    sys.exit(run())
