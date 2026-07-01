#!/usr/bin/env bash
# İmga v1 partner API — ilk ops token bootstrap (goal §3.1, handoff §4).
#
# Tavuk-yumurta: /v1/admin/* opsBearer ister ama ilk ops token yok. Bu script
# mint + admin_tokens INSERT'ini api container İÇİNDE tek python çağrısında yapar:
#   - HMAC hash container'dan ASLA çıkmaz (yalnız DB'ye yazılır)
#   - plaintext token YALNIZ BİR KEZ stdout'a basılır → güvenli kanalla VDD Ops'a
#
# Kullanım (sunucuda, deploy'dan sonra):
#   sudo IMGA_ENV=staging    bash infra/imga/bootstrap-ops-token.sh
#   sudo IMGA_ENV=production bash infra/imga/bootstrap-ops-token.sh
#   (varsa yeni token için: ... BOOTSTRAP_FORCE=1 ...)
set -euo pipefail

ENV="${IMGA_ENV:-${1:-}}"
if [[ "$ENV" != "production" && "$ENV" != "staging" ]]; then
  echo "HATA: IMGA_ENV=production|staging ver." >&2; exit 2
fi
COMPOSE="/opt/imga/infra/imga/${ENV}/docker-compose.yml"
[[ -f "$COMPOSE" ]] || { echo "HATA: compose yok: $COMPOSE" >&2; exit 2; }

FORCE="${BOOTSTRAP_FORCE:-0}"

echo "== İlk ops token mint + INSERT (${ENV}) =="
# Tek python: mint (container'daki IMGA_TOKEN_PEPPER ile) + admin_tokens INSERT
# (imga_admin BYPASSRLS; admin_tokens deny-all → app rolü yazamaz). Var olan
# canlı bootstrap token'ı varsa FORCE olmadıkça reddet (token sprawl'ı önle).
TOKEN="$(docker compose -f "$COMPOSE" exec -T \
  -e BOOTSTRAP_FORCE="$FORCE" api python - <<'PY'
import asyncio, os, sys
from imga_api.security.api_tokens import mint_token, OPS_LIVE_PREFIX, OPS_STG_PREFIX
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

env = os.environ.get("IMGA_ENV", "")
pepper = os.environ.get("IMGA_TOKEN_PEPPER", "")
force = os.environ.get("BOOTSTRAP_FORCE", "0") == "1"
if not pepper:
    print("ERR: IMGA_TOKEN_PEPPER container'da yok", file=sys.stderr); sys.exit(3)
prefix = OPS_LIVE_PREFIX if env == "production" else OPS_STG_PREFIX
url = os.environ.get("DATABASE_URL_ADMIN") or os.environ["DATABASE_URL_OWNER"]

async def main():
    eng = create_async_engine(url)
    try:
        async with eng.begin() as conn:
            existing = (await conn.execute(text(
                "SELECT count(*) FROM admin_tokens "
                "WHERE label='bootstrap' AND revoked_at IS NULL AND expires_at > now()"
            ))).scalar_one()
            if existing and not force:
                print(f"ERR: {existing} canlı bootstrap ops token zaten var; "
                      "yeni için BOOTSTRAP_FORCE=1", file=sys.stderr)
                sys.exit(4)
            t = mint_token(prefix=prefix, pepper=pepper)
            await conn.execute(text(
                "INSERT INTO admin_tokens(token_prefix, token_hash, last4, scope, "
                "label, expires_at) VALUES (:p, :h, :l, 'ops', 'bootstrap', "
                "now() + interval '365 days')"
            ), {"p": t.token_prefix, "h": t.token_hash, "l": t.last4})
        print(t.plaintext)   # YALNIZ plaintext stdout'a
    finally:
        await eng.dispose()

asyncio.run(main())
PY
)"

if [[ -z "${TOKEN:-}" ]]; then
  echo "HATA: token üretilemedi (üstteki stderr'e bak)." >&2; exit 1
fi

cat <<EOF

== OPS TOKEN (YALNIZ BİR KEZ GÖSTERİLİR) ==

  $TOKEN

- Bu token admin_tokens'a hash'li yazıldı; plaintext DB'de YOK, tekrar alınamaz.
- Güvenli kanalla VDD Ops'a ilet. Bununla:
    POST /v1/admin/tenants        → asakai-${ENV} tenant'ı oluştur
    POST /v1/admin/tokens/rotate  → tenant Bearer'ları mint et
- Kaybolursa: bu script'i BOOTSTRAP_FORCE=1 ile tekrar koş (yeni token, eskiyi revoke et).
EOF
