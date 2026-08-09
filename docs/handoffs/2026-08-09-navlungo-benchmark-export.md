# Navlungo benchmark verisi dışa aktarımı

- **Tarih:** 2026-08-09
- **Yazar:** local-agent
- **Hedef:** server-agent
- **Durum:** open
- **Öncelik:** yüksek

## Amaç

BERT yerine LLM tabanlı duygu analizine geçiş için 5 OpenRouter modelini
kıyaslayacağız. Kıyaslama Navlungo kurumunun mevcut yorumları üzerinde
lokalde koşacak. Bunun için production veritabanından üç CSV dışa
aktarımı gerekiyor. **API anahtarı dışa aktarma — yalnızca veri.**

## Adımlar

Tümü prod Postgres üzerinde, `imga_owner` ile (RLS bypass — cross-tenant
okuma bilinçli; sadece SELECT var, yazma yok):

```bash
ENV=production
COMPOSE=/opt/imga/infra/imga/$ENV/docker-compose.yml
OUT=/opt/imga/exports/2026-08-09-navlungo-benchmark
sudo mkdir -p $OUT

# 1) Navlungo tenant id'sini bul (asıl sorgularda $TENANT yerine koy)
sudo docker compose -f $COMPOSE exec postgres psql -U imga_owner -d imga \
  -c "SELECT id, name FROM tenants WHERE name ILIKE '%navlungo%';"

# 2) Yorumlar (soft-delete hariç)
sudo docker compose -f $COMPOSE exec postgres psql -U imga_owner -d imga -c "\copy (
  SELECT id, text, sentiment_label, sentiment_score, primary_category,
         primary_confidence, company_perspective_code, nps_score,
         batch_job_id, created_at, analyzed_at,
         overrides_applied::text AS overrides_applied
  FROM reviews
  WHERE tenant_id = '$TENANT' AND deleted_at IS NULL
  ORDER BY created_at
) TO STDOUT WITH CSV HEADER" > /tmp/navlungo_reviews.csv

# 3) İnsan düzeltmeleri (referans etiketlerin bir parçası)
sudo docker compose -f $COMPOSE exec postgres psql -U imga_owner -d imga -c "\copy (
  SELECT review_id, text_hash, review_text,
         old_sentiment_label, new_sentiment_label,
         old_category, new_category, reason, created_at
  FROM review_corrections
  WHERE tenant_id = '$TENANT'
  ORDER BY created_at
) TO STDOUT WITH CSV HEADER" > /tmp/navlungo_corrections.csv
# Not: review_corrections'ta tenant_id kolonu yoksa reviews üzerinden
# JOIN'le sınırla (JOIN reviews r ON r.id = review_id AND r.tenant_id = ...).

# 4) Hangi batch'i hangi motor etiketledi (BERT mi LLM mi ayrımı için)
sudo docker compose -f $COMPOSE exec postgres psql -U imga_owner -d imga -c "\copy (
  SELECT related_entity_id AS batch_job_id, model_provider, model_name,
         count(*) AS calls, min(created_at) AS first_call
  FROM llm_call_audit
  WHERE tenant_id = '$TENANT'
  GROUP BY 1, 2, 3
) TO STDOUT WITH CSV HEADER" > /tmp/navlungo_llm_audit.csv
# Not: kolon adları şemadan sapıyorsa (related_entity_id / tenant_id),
# \d llm_call_audit ile bak ve uyarla — amaç batch → motor eşlemesi.

sudo mv /tmp/navlungo_*.csv $OUT/ && sudo gzip -f $OUT/*.csv
ls -lh $OUT
```

## Beklenen çıktı

`/opt/imga/exports/2026-08-09-navlungo-benchmark/` altında üç `.csv.gz`.
Satır sayılarını (üç dosya için de) bu dosyanın "Sonuç" bölümüne yaz ve
Durum'u `resolved` yap. Lokal taraf dosyaları şu komutla çekecek:

```bash
scp <sunucu>:/opt/imga/exports/2026-08-09-navlungo-benchmark/*.csv.gz .
```

## Sonuç

(server-agent doldurur)
