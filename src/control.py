"""
Controle dos jobs pelo banco (painel Predator do ares-web2).

O ares-web2 grava a configuração em `predator_jobs` (liga/desliga, intervalos,
pausa, "rodar agora"). Aqui o predator lê essa tabela para decidir o que rodar
e registra cada execução em `predator_execucoes`.

Contrato completo: ares-web2/docs/predator2.md
Schema:           ares-web2/db/migrations/001_predator_control.sql

Se as tabelas ainda não existirem (migration não aplicada), `JobControl.available`
retorna False e o sync roda no modo antigo (todos os relatórios).
"""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass, field

import psycopg2

from src.db.writer import get_db

log = logging.getLogger(__name__)

HOST = os.environ.get("PREDATOR_HOST") or socket.gethostname()
VERSAO = os.environ.get("PREDATOR_VERSION", "predator2")

# Folga para o cron de 1 em 1 minuto não "perder" a janela por segundos.
FOLGA = "45 seconds"


@dataclass
class Job:
    id: str                 # id no banco, ex.: "r106"
    report_id: str          # id do relatório no Brudam, ex.: "106"
    nome: str
    origem: str             # "agendado" | "manual"
    parametros: dict = field(default_factory=dict)
    exec_id: int | None = None


def job_to_report_id(job_id: str) -> str:
    return job_id[1:] if job_id.startswith("r") else job_id


class JobControl:
    def __init__(self) -> None:
        self.conn = get_db()
        self.conn.autocommit = True

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    # ── Disponibilidade ──────────────────────────────────────────────
    def available(self) -> bool:
        with self.conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.predator_jobs_status') IS NOT NULL")
            return bool(cur.fetchone()[0])

    # ── Limpeza de execuções travadas ────────────────────────────────
    def cleanup_stale(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE predator_execucoes e
                   SET status = 'timeout',
                       finalizado_em = now(),
                       duracao_ms = (EXTRACT(EPOCH FROM now() - e.iniciado_em) * 1000)::int,
                       erro = COALESCE(e.erro, 'Execução abandonada (processo morreu ou passou do timeout)')
                  FROM predator_jobs j
                 WHERE j.id = e.job_id
                   AND e.status = 'executando'
                   AND e.iniciado_em < now() - make_interval(secs => j.timeout_seg)
                """
            )
            if cur.rowcount:
                log.warning(f"[control] {cur.rowcount} execução(ões) travada(s) marcada(s) como timeout")
            return cur.rowcount

    # ── O que está vencido ───────────────────────────────────────────
    def due_jobs(self) -> list[Job]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, nome, parametros,
                       (execucao_solicitada_em IS NOT NULL
                        AND execucao_solicitada_em > COALESCE(ultimo_inicio, '-infinity'::timestamptz)) AS manual
                  FROM predator_jobs_status
                 WHERE ultimo_status IS DISTINCT FROM 'executando'
                   AND (
                        (execucao_solicitada_em IS NOT NULL
                         AND execucao_solicitada_em > COALESCE(ultimo_inicio, '-infinity'::timestamptz))
                     OR (ativo
                         AND (pausado_ate IS NULL OR pausado_ate <= now())
                         AND proxima_execucao_prevista <= now() + interval '{FOLGA}')
                   )
                 ORDER BY ordem, id
                """
            )
            return [
                Job(
                    id=row[0],
                    report_id=job_to_report_id(row[0]),
                    nome=row[1],
                    parametros=row[2] or {},
                    origem="manual" if row[3] else "agendado",
                )
                for row in cur.fetchall()
            ]

    # ── Início / fim de execução ─────────────────────────────────────
    def start(self, job: Job) -> bool:
        """Registra o início. Retorna False se o job já está rodando (trava única)."""
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO predator_execucoes (job_id, origem, status, host, versao)
                    VALUES (%s, %s, 'executando', %s, %s)
                    RETURNING id
                    """,
                    (job.id, job.origem, HOST, VERSAO),
                )
                job.exec_id = cur.fetchone()[0]
                return True
        except psycopg2.errors.UniqueViolation:
            log.info(f"[control] {job.id} já está em execução em outro processo — pulando")
            return False

    def finish(self, job: Job, status: str, registros: int | None = None,
               erro: str | None = None, log_text: str | None = None) -> None:
        if job.exec_id is None:
            return
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE predator_execucoes
                   SET status = %s,
                       finalizado_em = now(),
                       duracao_ms = (EXTRACT(EPOCH FROM now() - iniciado_em) * 1000)::int,
                       registros = %s,
                       erro = %s,
                       log = %s
                 WHERE id = %s AND status = 'executando'
                """,
                (status, registros, (erro or None) and erro[:4000],
                 (log_text or None) and log_text[-20000:], job.exec_id),
            )
        job.exec_id = None
