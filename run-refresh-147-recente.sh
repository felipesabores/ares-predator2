#!/bin/bash
# Refresh noturno do relatório 147 (últimos 35 dias).
# Mantém custos_operacao_historico atualizado com os reajustes que o Brudam
# faz retroativamente em operações recentes (custo, margem, lucro líquido).
#
# Roda 1x por noite via crontab (ex.: 23:30, após o sync diário).
# O backfill completo mensal (run-backfill-147.sh) continua rodando no dia 1
# para cobrir meses mais antigos.
#
# Log persistente em backfill.log (mesmo arquivo do backfill completo).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S') Refresh 147 recente (65d) start ===" >> backfill.log
python3 backfill_147.py --dias 65 >> backfill.log 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') Refresh 147 recente (65d) end ===" >> backfill.log
