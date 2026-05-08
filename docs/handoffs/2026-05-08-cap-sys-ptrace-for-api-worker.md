# Handoff: cap-sys-ptrace-for-api-worker

**Tarih:** 2026-05-08
**Sprint:** 9.0.5-A R7 follow-up
**Yazar:** server-agent
**Hedef:** local-agent
**Durum:** open
**Öncelik:** orta

## Bağlam

Sprint 9.0.5-A R5/R6 turlarında batch worker takılması debug edilmek
istendiğinde py-spy stack dump alınamadı: Docker default capability
set'i `CAP_SYS_PTRACE`'i çıkarıyor, `py-spy dump` "Operation not
permitted" ile failed olur (root user içinde bile). R7 deploy sonrası
smoke test'te SDK timeout / circuit breaker davranışını gözlemleyebilmek
için worker'a kalıcı ptrace cap'i lazım.

Sunucu ajan compose'lara `cap_add: [SYS_PTRACE]` ekledi (sadece
api-worker, api ve postgres dokunulmadı — saldırı yüzeyini minimal
tutmak için).

## Talep

`infra/imga/{production,staging}/docker-compose.yml` dosyalarındaki
working tree değişikliklerini local repo'da uygula, **tek commit** +
push. Server agent git identity yok; kanonik patch flow.

## Beklenen çıktı

`origin/main` üzerinde tek commit:

ops(infra): cap_add SYS_PTRACE on api-worker for py-spy debug (Sprint 9.0.5-A R7 follow-up)

Docker default cap set ptrace'i blokluyor; batch worker takılma /
SDK timeout debug'unda py-spy dump --pid 1 attach edemiyor.
api-worker container'ı tek-noktadan izole edildiği için cap'i
sadece oraya veriyoruz; api ve postgres'te ptrace yok.

Production: imga-prod-api-worker
Staging:    imga-staging-api-worker

Push sonrası bu handoff'u `Cevap` bölümünde commit hash ile resolve et.

## Diff özeti

- `infra/imga/production/docker-compose.yml`: api-worker block'una `cap_add: [SYS_PTRACE]` + 3 satır comment
- `infra/imga/staging/docker-compose.yml`: api-worker block'una `cap_add: [SYS_PTRACE]` + 2 satır comment
- `docs/handoffs/INDEX.md`: bu handoff aktif handoff tablosunun üstüne eklendi

## Doğrulama (server agent yaptı)

- `git diff --stat`: 2 dosya, 10 insert, 0 delete (yorum satırları dahil)
- `docker compose -f .../production/docker-compose.yml config --services` → 5 service, syntax OK
- `docker compose -f .../staging/docker-compose.yml config --services` → 5 service, syntax OK
- Build/up bu commit'e bağlanmadı; R7 application code push'undan sonra birlikte rebuild + force-recreate olacak (server agent koşturacak).

## Post-demo review TODO

R7 demo başarısı + 1 hafta stable çalışma sonrası `cap_add: [SYS_PTRACE]` kaldırma kararı yeniden değerlendirilecek. İki seçenek:
- A (önerilen): Bırak. Worker internal network'te (caddy-public'te değil), saldırı yüzeyi düşük; 9.x sprint'lerinde performance regression debug'unda tekrar ihtiyaç olabilir.
- B: Demo + 1 hafta sabit çalıştıktan sonra kaldır (`revert ops: cap_add SYS_PTRACE removal post-9.0.5-A demo`).

Local-agent post-demo review'a `A önerilen` notuyla katıldı; karar demo + 1 hafta sonrasına ertelendi.

## Cevap

**Resolved:** `d02ae16`
**Push doğrulama:** `f9bd89a..d02ae16` → `origin/main`
**Tarih:** 2026-05-08
**Local agent:** Patch flow yerine doğrudan üç dosya editi + yeni handoff dosyası olarak uygulandı (Windows local repo'da CRLF/LF line-ending pain'inden kaçınmak için; sonuç birebir aynı, 4 dosya / 11 insert). Sprint 9.0.5-A R7 application code commit'leri (en son `f9bd89a`) ile birlikte tek pull/build döngüsünde deploy edilebilir.
**Tag durumu:** `sprint-9.0.5-A` tag `7ecf1e6`'da kalır (R7 follow-up SDK test commit'i). Bu ops infra commit sprint code scope'unda değil; tag taşımadık.
