#!/usr/bin/env bash
# Smoke tests do Painel Comercial — chamado via cron hourly.
# Log rotativo simples; mantém últimos 7 dias.

set -u
cd /Users/felipecarvalho/ares-predator

LOG_DIR=/Users/felipecarvalho/ares-predator/.smoke-logs
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/smoke-$(date +%Y%m%d).log"

{
  echo
  echo "═══════════════════════════════════════════"
  echo " $(date '+%Y-%m-%d %H:%M:%S %Z') — run"
  echo "═══════════════════════════════════════════"
  /usr/bin/env python3 -m src.smoke.smoke_tests_comercial
  status=$?
  echo "exit: $status"
} >> "$LOG_FILE" 2>&1

# Limpa logs > 7 dias
find "$LOG_DIR" -name "smoke-*.log" -mtime +7 -delete 2>/dev/null

exit 0
