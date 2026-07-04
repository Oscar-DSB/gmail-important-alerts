#!/usr/bin/env bash
# Sube los secretos necesarios como GitHub Secrets del repositorio, usando
# la CLI de gh (requiere `gh auth login` ya hecho y estar dentro del repo,
# o pasar --repo owner/name).
#
# Uso:
#   export GEMINI_API_KEY="..."
#   export TELEGRAM_BOT_TOKEN="..."
#   export TELEGRAM_CHAT_ID="..."
#   export UPSTASH_REDIS_REST_URL="..."
#   export UPSTASH_REDIS_REST_TOKEN="..."
#   ./scripts/setup_github_secrets.sh
#
# El token de Gmail (gmail_token.json, generado por setup_gmail_oauth.py)
# se sube aparte, leyendo directamente el archivo.

set -euo pipefail

require_var() {
  local var_name="$1"
  if [[ -z "${!var_name:-}" ]]; then
    echo "Falta la variable de entorno $var_name. Expórtala antes de ejecutar este script."
    exit 1
  fi
}

require_var GEMINI_API_KEY
require_var TELEGRAM_BOT_TOKEN
require_var TELEGRAM_CHAT_ID
require_var UPSTASH_REDIS_REST_URL
require_var UPSTASH_REDIS_REST_TOKEN

gh secret set GEMINI_API_KEY --body "$GEMINI_API_KEY"
gh secret set TELEGRAM_BOT_TOKEN --body "$TELEGRAM_BOT_TOKEN"
gh secret set TELEGRAM_CHAT_ID --body "$TELEGRAM_CHAT_ID"
gh secret set UPSTASH_REDIS_REST_URL --body "$UPSTASH_REDIS_REST_URL"
gh secret set UPSTASH_REDIS_REST_TOKEN --body "$UPSTASH_REDIS_REST_TOKEN"

if [[ -f "gmail_token.json" ]]; then
  gh secret set GMAIL_OAUTH_TOKEN_JSON < gmail_token.json
  echo "GMAIL_OAUTH_TOKEN_JSON subido desde gmail_token.json."
else
  echo "No se encontró gmail_token.json en el directorio actual."
  echo "Ejecuta primero: python scripts/setup_gmail_oauth.py"
  echo "y vuelve a correr este script, o súbelo manualmente:"
  echo "  gh secret set GMAIL_OAUTH_TOKEN_JSON < gmail_token.json"
fi

echo
echo "Secretos configurados. Verifica con: gh secret list"
