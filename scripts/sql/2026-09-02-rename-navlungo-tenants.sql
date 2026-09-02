-- 2026-09-02 — Navlungo adlı test kurumlarını nötr adlara çevir (ürün
-- sahibi talebi: demo/sunumlarda müşteri adı görünmesin).
-- Beş kurum vardı (üçü "Navlungo" adında); kullanıcı 3 ad verdi, kalan
-- ikisi n-test4 / n-test5 olarak devam eder. İdempotent.
BEGIN;
UPDATE tenants SET name = 'n-test1', slug = 'n-test1' WHERE id = 'af347ecc-4527-435d-ba81-8c962c947821'; -- Navlungo (navlungo, 675 yorum)
UPDATE tenants SET name = 'n-test2', slug = 'n-test2' WHERE id = 'ebff0a6f-5ddb-48c6-b4ba-7263153d7c50'; -- Navlungo Test (25.989 yorum)
UPDATE tenants SET name = 'n-test3', slug = 'n-test3' WHERE id = 'b2ec3848-e83a-47a9-b51f-520bd6211872'; -- NAVLUNGO TEST 2 (17.751 yorum)
UPDATE tenants SET name = 'n-test4', slug = 'n-test4' WHERE id = '22a6ceb0-f617-4ae7-9b77-ec988914ce18'; -- Navlungo (navlungo-tr, 477 yorum)
UPDATE tenants SET name = 'n-test5', slug = 'n-test5' WHERE id = '852a909f-e068-453b-8185-30c49ced9e68'; -- Navlungo (navlungonavlungo, 0 yorum)
COMMIT;
SELECT name, slug FROM tenants WHERE slug LIKE 'n-test%' OR name ILIKE '%navlungo%' ORDER BY name;
