# Deploy Prompt — İmga v1: SSE gerçek-streaming + prompt v2/grounding

**Tarih:** 2026-07-01 · **Yazar:** local-agent → server-agent · **Hedef commit:** `f50087c` (main HEAD)
**Son prod deploy:** `9ec03ac` (auth-rollback cutover) → bu deploy aradaki her şeyi getirir.

## Ne deploy oluyor (9ec03ac → f50087c)
- **SSE gerçek token-streaming** (`33948a3`): `free-analyze` artık `generate_content_stream`
  ile token-by-token akıyor (ilk-token TTFT). `imga_core.stream_text` google-genai async
  yüzeyinin iki şekline de dayanıklı (`inspect.isawaitable`).
- **Prompt v2 + grounding** (`fb5496e`, `f50087c`): use-case system promptları misyon-hizalı
  (olmayan sorunu şişirmez) + anti-hallucination (yalnız context'teki veriden). cargo-optimize
  artık listede olmayan/gereksiz kargo firması önermez; yetersiz veride `carrier=""` + reason.
- **Şema/migration YOK** — contract §4 shape aynı, DDL değişmedi → `alembic upgrade` GEREKMEZ.

## Deploy (aynı api container — v1 ayrı servis değil)
```bash
cd /opt/imga && git pull origin main            # f50087c gelir
COMPOSE=/opt/imga/infra/imga/production/docker-compose.yml
sudo docker compose -f $COMPOSE build api
sudo docker compose -f $COMPOSE up -d api        # migration YOK
curl -sS https://api.imga.ai/v1/health | jq .status     # "ok" bekle
```

## ⚠️ KRİTİK — canlı SSE doğrulama (yerelde doğrulanamayan tek parça)
`generate_content_stream` SDK çağrı şekli yerelde (google-genai+key yok) doğrulanamadı;
mantık test compose'da yeşil ama gerçek SDK ancak canlıda görülür. **RELY ETMEDEN ÖNCE test et:**
```bash
TENANT_BEARER=<asakai-production tenant Bearer>          # cutover'da rotate edilen
CRID=$(python3 -c "import uuid;print(uuid.uuid4())")
TOK=$(curl -sS -X POST https://api.imga.ai/v1/analyze/free-analyze/stream-token \
  -H "Authorization: Bearer $TENANT_BEARER" -H "Content-Type: application/json" \
  -d "{\"tenant_id\":\"asakai-production\",\"use_case\":\"free-analyze\",\"context\":{},\"user_prompt\":\"Kısa bir sistem testi cevabı ver\",\"client_request_id\":\"$CRID\"}" \
  | jq -r .stream_token)
curl -N "https://api.imga.ai/v1/analyze/stream?token=$TOK"
```
- **GREEN:** `: ping` → `event: partial` (delta'lar AKIYOR) → `event: meta`
  (`tokens`+`cost_try`+`processed_in:"outbound"`) → `event: done`. İlk partial gelme süresini not et (<800ms hedefi).
- **RED** (500 / `event: error` / hiç partial / hang): SSE SDK çağrı şekli uyumsuz →
  **ROLLBACK yalnız SSE:**
  ```bash
  git revert --no-edit 33948a3
  sudo docker compose -f $COMPOSE build api && sudo docker compose -f $COMPOSE up -d api
  ```
  (Non-stream `/v1/analyze`, auth, admin, data ETKİLENMEZ; prompt v2 kalır.)

## Prompt v2 / cargo doğrulama (opsiyonel ama önerilir)
Gerçek `cargo_history` içeren bir cargo-optimize çağrısı at; doğrula:
- `suggestion.carrier` **yalnız gönderdiğin cargo_history'deki** bir firma (uydurma yok).
- Mevcut firma iyiyse gereksiz **switch önermiyor**; `risk_flags` olmayan riski işaretlemiyor.
- Boş cargo_history → `carrier=""` + reason "yetersiz veri" (null DEĞİL — owner kararı).

## Raporla
1. `/v1/health` + SSE event akışı (ilk-token gecikmesi) → §2.4 SSE alt-kriterini gerçek ölçümle kapatırım.
2. cargo-optimize örnek yanıtı (hallucination gitti mi).
3. RED olduysa tam çıktı → local-agent tek-satır düzeltir.
