#!/bin/bash
# Backfill mensal do relatório 147 (Custo por Operação).
# Sobrescreve custos_operacao_historico com snapshot fresco do Brudam
# em chunks de 1 mês (Jan/25 → hoje).
#
# Agendado no crontab pra rodar mensalmente — mantém o overlap com o
# sync diário consistente (sem drift de ops fechando tarde).
#
# Log persistente em backfill.log pra debug pós-mortem.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
fi

# Carrega funções de notificação
source "$SCRIPT_DIR/ntfy-sync-alert.sh"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') Backfill 147 start ===" >> backfill.log

START=$(date +%s)
python3 backfill_147.py >> backfill.log 2>&1
EXIT_CODE=$?
ELAPSED=$(( $(date +%s) - START ))
DURATION="${ELAPSED}s"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') Backfill 147 end (exit $EXIT_CODE) ===" >> backfill.log

NTFY_URL="https://orangepizero3.tail0b0ed.ts.net"
NTFY_AUTH="${NTFY_AUTH:-$(grep -E '^NTFY_AUTH=' "$(dirname "$0")/.env" 2>/dev/null | head -1 | cut -d= -f2-)}"

if [ $EXIT_CODE -eq 0 ]; then
    curl -s -u "$NTFY_AUTH" \
        -H "Title: Oráculo — ✅ Backfill 147 OK" \
        -H "Tags: white_check_mark,bar_chart" \
        -H "Priority: low" \
        -d "Backfill custos_operacao_historico concluido em $DURATION" \
        "$NTFY_URL/scraper" > /dev/null 2>&1
else
    curl -s -u "$NTFY_AUTH" \
        -H "Title: Oráculo — 🚨 Backfill 147 FALHOU" \
        -H "Tags: rotating_light,bar_chart" \
        -H "Priority: urgent" \
        -H "Click: https://ares.acertaexpress.app/system-health" \
        -d "Backfill falhou (exit $EXIT_CODE) após $DURATION — ver backfill.log" \
        "$NTFY_URL/scraper" > /dev/null 2>&1
fi
