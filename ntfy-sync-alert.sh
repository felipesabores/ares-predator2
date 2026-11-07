#!/bin/bash
# Ntfy alert helper - adicionar no final do run-sync.sh
# Uso: source ntfy-sync-alert.sh

NTFY_URL="https://orangepizero3.tail0b0ed.ts.net"
# NTFY_AUTH (usuario:senha) vem do .env — ver .env.example
if [ -z "${NTFY_AUTH:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/.env" ]; then
    NTFY_AUTH=$(grep -E '^NTFY_AUTH=' "$(dirname "${BASH_SOURCE[0]}")/.env" | head -1 | cut -d= -f2-)
fi

ntfy_ok() {
    curl -s -u "$NTFY_AUTH" \
        -H "Title: Oráculo — ✅ Sync OK" \
        -H "Tags: white_check_mark" \
        -H "Priority: low" \
        -d "Sync concluido em $(date '+%H:%M') - $1" \
        "$NTFY_URL/scraper" > /dev/null 2>&1
}

ntfy_fail() {
    curl -s -u "$NTFY_AUTH" \
        -H "Title: Oráculo — 🚨 Sync FALHOU" \
        -H "Tags: rotating_light" \
        -H "Priority: urgent" \
        -H "Click: https://ares.acertaexpress.app/system-health" \
        -d "Falha no sync $(date '+%H:%M') - $1" \
        "$NTFY_URL/scraper" > /dev/null 2>&1
}

ntfy_backup_ok() {
    curl -s -u "$NTFY_AUTH" \
        -H "Title: Oráculo — ✅ Backup OK" \
        -H "Tags: white_check_mark,floppy_disk" \
        -H "Priority: low" \
        -d "Dump PG concluido - $1" \
        "$NTFY_URL/backup" > /dev/null 2>&1
}

ntfy_backup_fail() {
    curl -s -u "$NTFY_AUTH" \
        -H "Title: Oráculo — 🚨 Backup FALHOU" \
        -H "Tags: rotating_light,floppy_disk" \
        -H "Priority: urgent" \
        -d "Dump PG falhou - $1" \
        "$NTFY_URL/backup" > /dev/null 2>&1
}
