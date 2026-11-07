#!/bin/bash
# deploy.sh — Push + notifica via Ntfy (+ Dokploy deploy pra ares-web)
# Uso: ./deploy.sh [mensagem opcional]

set -e

NTFY_URL="https://orangepizero3.tail0b0ed.ts.net"
NTFY_AUTH="${NTFY_AUTH:-$(grep -E '^NTFY_AUTH=' "$(dirname "$0")/.env" 2>/dev/null | head -1 | cut -d= -f2-)}"
TOPIC="ares"

DOKPLOY_URL="http://173.249.15.221:3000"
DOKPLOY_TOKEN="${DOKPLOY_TOKEN:-$(grep -E '^DOKPLOY_TOKEN=' "$(dirname "$0")/.env" 2>/dev/null | head -1 | cut -d= -f2-)}"

# Detecta repo
REPO_NAME=$(basename "$(git rev-parse --show-toplevel)")
BRANCH=$(git branch --show-current)

# Pega commits que vão ser pushados
COMMITS=$(git log origin/$BRANCH..$BRANCH --oneline 2>/dev/null)
COMMIT_COUNT=$(echo "$COMMITS" | grep -c . 2>/dev/null || echo "0")

if [ "$COMMIT_COUNT" -eq 0 ]; then
    echo "Nada pra pushar."
    exit 0
fi

echo "📦 $REPO_NAME — $COMMIT_COUNT commit(s) pra pushar:"
echo "$COMMITS"
echo ""

# Push
echo "🚀 Pushando..."
git push

# Monta mensagem
CHANGES=$(echo "$COMMITS" | sed 's/^[a-f0-9]* /• /')
MSG="$COMMIT_COUNT commit(s) em $BRANCH:
$CHANGES"

# Notifica
if [ "$REPO_NAME" = "ares-web" ]; then
    # Dispara deploy no Dokploy
    echo "🔄 Disparando deploy no Dokploy..."

    # Busca applicationId do ares-web
    APP_ID=$(curl -s -H "x-api-key: $DOKPLOY_TOKEN" "$DOKPLOY_URL/api/application.all" 2>/dev/null \
        | python3 -c "import sys,json; apps=json.load(sys.stdin); print(next((a['applicationId'] for a in apps if 'ares' in a.get('name','').lower()), ''))" 2>/dev/null)

    if [ -n "$APP_ID" ]; then
        DEPLOY_RESULT=$(curl -s -X POST \
            -H "x-api-key: $DOKPLOY_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"applicationId\":\"$APP_ID\"}" \
            "$DOKPLOY_URL/api/application.deploy" 2>/dev/null)

        curl -s -u "$NTFY_AUTH" \
            -H "Title: Oráculo — 🚀 Deploy $REPO_NAME" \
            -H "Priority: high" \
            -H "Tags: rocket,hammer_and_wrench" \
            -H "Click: https://ares.acertaexpress.app" \
            -d "$MSG

Deploy disparado no Dokploy" \
            "$NTFY_URL/$TOPIC" > /dev/null 2>&1

        echo "✅ Deploy disparado + notificação enviada"
    else
        curl -s -u "$NTFY_AUTH" \
            -H "Title: Oráculo — 🚀 Push $REPO_NAME" \
            -H "Priority: high" \
            -H "Tags: rocket" \
            -d "$MSG

⚠️ Deploy Dokploy nao disparado (app nao encontrado)" \
            "$NTFY_URL/$TOPIC" > /dev/null 2>&1

        echo "⚠️ Push OK mas app não encontrada no Dokploy"
    fi
else
    # ares-predator — só notifica (box faz git pull no próximo cron)
    curl -s -u "$NTFY_AUTH" \
        -H "Title: Oráculo — 📦 Push $REPO_NAME" \
        -H "Priority: default" \
        -H "Tags: package,white_check_mark" \
        -d "$MSG

Box atualiza no proximo cron" \
        "$NTFY_URL/$TOPIC" > /dev/null 2>&1

    echo "✅ Push + notificação enviada (box pega no próximo cron)"
fi
