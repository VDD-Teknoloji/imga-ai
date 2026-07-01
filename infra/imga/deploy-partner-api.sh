#!/usr/bin/env bash
# İmga v1 partner API — deploy (goal §3.11). Handoff'un çalıştırılabilir hali:
#   docs/handoffs/2026-07-01-asakai-n1-deploy-and-cutover.md
#
# v1 AYRI servis DEĞİL — mevcut FastAPI `api` container'ına /v1/* route olarak
# biner. Deploy = api image rebuild + migration + (Caddy ayrı, bir kez).
#
# Kullanım (sunucuda, /opt/imga içinde):
#   sudo IMGA_ENV=staging    bash infra/imga/deploy-partner-api.sh
#   sudo IMGA_ENV=production bash infra/imga/deploy-partner-api.sh
#
# GÜVENLİK: bu script secret ÜRETMEZ ve YAZMAZ. IMGA_TOKEN_PEPPER + GEMINI_API_KEY
# api.env'de OLMALI (sen sağlarsın). Eksikse deploy etmez (fail-fast).
set -euo pipefail

ENV="${IMGA_ENV:-${1:-}}"
if [[ "$ENV" != "production" && "$ENV" != "staging" ]]; then
  echo "HATA: IMGA_ENV=production|staging ver (arg veya env)." >&2
  exit 2
fi

COMPOSE="/opt/imga/infra/imga/${ENV}/docker-compose.yml"
ENV_FILE="/etc/imga/${ENV}/api.env"

echo "== [1/5] Ön-koşul: env + secret kontrolü (${ENV}) =="
[[ -f "$COMPOSE" ]]  || { echo "HATA: compose yok: $COMPOSE" >&2; exit 2; }
[[ -f "$ENV_FILE" ]] || { echo "HATA: api.env yok: $ENV_FILE" >&2; exit 2; }

# Değerleri YAZDIRMADAN yalnız varlığını + min-uzunluğunu doğrula.
require_secret() {
  local key="$1" minlen="$2"
  local val
  val="$(grep -E "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
  if [[ -z "$val" ]]; then
    echo "HATA: $key $ENV_FILE içinde yok/boş. Deploy iptal." >&2; exit 3
  fi
  if (( ${#val} < minlen )); then
    echo "HATA: $key çok kısa (< ${minlen}). Deploy iptal." >&2; exit 3
  fi
  echo "  ok: $key mevcut (${#val} karakter)"
}
require_secret IMGA_TOKEN_PEPPER 32
require_secret GEMINI_API_KEY 20

# IMGA_ENV prefix enforcement için doğru olmalı.
if ! grep -qE "^IMGA_ENV=${ENV}$" "$ENV_FILE"; then
  echo "UYARI: $ENV_FILE içinde IMGA_ENV=${ENV} satırı görülmedi — cross-env token" >&2
  echo "       reddi (imga_live_/imga_stg_) buna bağlı; kontrol et." >&2
fi

echo "== [2/5] git pull origin main =="
git -C /opt/imga pull --ff-only origin main

echo "== [3/5] api image rebuild + up =="
docker compose -f "$COMPOSE" build api
docker compose -f "$COMPOSE" up -d api

echo "== [4/5] alembic upgrade head (0031 -> 0034) =="
docker compose -f "$COMPOSE" exec -T api alembic upgrade head

echo "== [5/5] /v1/health smoke (container içi 127.0.0.1) =="
# CLAUDE.md healthcheck kuralı: localhost değil 127.0.0.1 (BusyBox IPv6 fallback yok).
if docker compose -f "$COMPOSE" exec -T api python -c \
  "import urllib.request,sys,json; r=json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/health',timeout=5)); print('  health:',r['status'],'| providers:',r['providers']); sys.exit(0 if r['status'] in ('ok','degraded') else 1)"; then
  echo "  ok: /v1/health yanıt verdi."
else
  echo "UYARI: /v1/health smoke başarısız — port/servis adını compose'da doğrula." >&2
fi

if [[ "$ENV" == "production" ]]; then
  HOST="api.imga.ai"; TAGPREFIX="prod"
else
  HOST="api-staging.imga.ai"; TAGPREFIX="staging"
fi
cat <<EOF

== Deploy tamam (${ENV}). SONRAKİ (bir kez / ayrı) ==
  - Caddy route: /opt/shared/caddy/conf.d/imga-*.conf (${HOST} -> api:8000),
    'caddy reload'. Yeni container ise şart.
  - İlk ops token: infra/imga/bootstrap-ops-token.sh (tavuk-yumurta; bir kez).
  - Uptime robot: GET https://${HOST}/v1/health / 60sn.
  - Deploy tag: git tag ${TAGPREFIX}-v1.3.X && git push --tags
EOF
