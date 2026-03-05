#!/usr/bin/env bash
# Query Service 冒烟脚本（不回显 token）
# 用法: ./scripts/smoke_query_service.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

safe_load_env() {
    local file="$1"
    [ -f "$file" ] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*export ]] && continue
        [[ "$line" =~ \$\( ]] && continue
        [[ "$line" =~ \` ]] && continue
        if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
            local key="${BASH_REMATCH[1]}"
            local val="${BASH_REMATCH[2]}"
            val="${val#\"}" && val="${val%\"}"
            val="${val#\'}" && val="${val%\'}"
            export "$key=$val"
        fi
    done < "$file"
}

ENV_FILE="$ROOT/assets/config/.env"
if [ ! -f "$ENV_FILE" ] && [ -f "$ROOT/config/.env" ]; then
    ENV_FILE="$ROOT/config/.env"
fi
safe_load_env "$ENV_FILE"

BASE="${QUERY_SERVICE_BASE_URL:-http://127.0.0.1:8088}"
BASE="${BASE%/}"
MODE="${QUERY_SERVICE_AUTH_MODE:-required}"
MODE="$(echo "$MODE" | tr '[:upper:]' '[:lower:]' | xargs)"
[ -z "$MODE" ] && MODE="required"

echo "=== Query Service Smoke ==="
echo "base_url=$BASE"
echo "auth_mode=$MODE"

no_token_ok=0
resp="$(curl -s --max-time 2 "$BASE/api/v1/health" || true)"
if echo "$resp" | grep -q '"msg":"unauthorized"'; then
    no_token_ok=1
fi
echo "health(no_token)=$( [ $no_token_ok -eq 1 ] && echo unauthorized_ok || echo unexpected )"

if [ "$MODE" = "disabled" ] || [ "$MODE" = "off" ]; then
    if echo "$resp" | grep -q '"success":true'; then
        echo "health(auth)=success_ok (auth disabled)"
        exit 0
    fi
    echo "health(auth)=FAILED (auth disabled but not success)"
    exit 1
fi

if [ -z "${QUERY_SERVICE_TOKEN:-}" ] || [ "${QUERY_SERVICE_TOKEN:-}" = "dev-token-change-me" ] || [ "${QUERY_SERVICE_TOKEN:-}" = "your_token_here" ]; then
    echo "❌ QUERY_SERVICE_TOKEN 未配置或为默认占位值（拒绝继续）"
    exit 1
fi

resp2="$(curl -s --max-time 2 -H "X-Internal-Token: $QUERY_SERVICE_TOKEN" "$BASE/api/v1/health" || true)"
if echo "$resp2" | grep -q '"success":true'; then
    echo "health(auth)=success_ok"
else
    echo "health(auth)=FAILED"
    exit 1
fi

resp3="$(curl -s --max-time 3 -H "X-Internal-Token: $QUERY_SERVICE_TOKEN" "$BASE/api/v1/capabilities" || true)"
if echo "$resp3" | grep -q '"success":true'; then
    echo "capabilities=success_ok"
else
    echo "capabilities=FAILED"
    exit 1
fi

echo "✅ smoke ok"
