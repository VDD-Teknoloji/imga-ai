-- 2026-09-02 — KVKK: reviews.source_url anonimleştirme (TASK B2 / PART 1)
--
-- Prodüksiyonda mevcut 677 Twitter satırının TAMAMI source_url alanında
-- yazar hesap adını taşıyor bulundu: https://x.com/<handle>/status/<id>.
-- Bu, "yazar kimliği hiçbir yerde kalıcı yazılmaz" kuralının ihlaliydi —
-- URL içindeki hesap adı da kimliktir. Kod tarafı (twitter_import.py,
-- tweet_url_from_item) artık HER ZAMAN hesap adı içermeyen kanonik biçimi
-- (https://x.com/i/web/status/{id}) üretiyor; bu betik GEÇMİŞ satırları
-- aynı biçime tek seferlik geri dönüştürür.
--
-- İdempotent: WHERE koşulu zaten kanonik biçimde olan satırları
-- (source_url'de "/i/web/status/" geçenleri) dışlar, script iki kez
-- çalıştırılsa ikinci çalıştırma hiçbir satırı etkilemez (regexp koşulu
-- artık eşleşmez).
--
-- Kullanım (prod):
--   sudo docker compose -f $COMPOSE exec postgres \
--     psql -U imga_owner -d imga -f /path/to/this/file.sql
-- (imga_owner RLS'i atlar — kurum sınırı olmadan TÜM satırları düzeltir;
-- bu satır bazlı bir veri temizliği, kurum-özel bir işlem değil.)

-- Öncesi: kaç satır hâlâ hesap adı taşıyan eski biçimde?
-- SELECT count(*) FROM reviews
-- WHERE source_url ~ '^https?://(x|twitter)\.com/[^/]+/status/[0-9]+'
--   AND source_url !~ '/i/web/status/';

UPDATE reviews
SET source_url = regexp_replace(
    source_url,
    '^https?://(x|twitter)\.com/[^/]+/status/([0-9]+).*$',
    'https://x.com/i/web/status/\2'
)
WHERE source_url ~ '^https?://(x|twitter)\.com/[^/]+/status/[0-9]+'
  AND source_url !~ '/i/web/status/';

-- Sonrası: 0 olmalı (tüm eski biçimli satırlar dönüştürüldü).
-- SELECT count(*) FROM reviews
-- WHERE source_url ~ '^https?://(x|twitter)\.com/[^/]+/status/[0-9]+'
--   AND source_url !~ '/i/web/status/';
