#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Ativa o venv se existir
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
fi

# Carrega funções de notificação
source "$SCRIPT_DIR/ntfy-sync-alert.sh"

# Roda sync e captura resultado
START=$(date +%s)
python3 sync.py
EXIT_CODE=$?
ELAPSED=$(( $(date +%s) - START ))
DURATION="${ELAPSED}s"

# 75 = nada vencido no painel (cron roda a cada minuto) → não notifica
if [ $EXIT_CODE -eq 75 ]; then
    exit 0
elif [ $EXIT_CODE -eq 0 ]; then
    ntfy_ok "relatórios em $DURATION"
else
    ntfy_fail "exit code $EXIT_CODE após $DURATION"
fi
