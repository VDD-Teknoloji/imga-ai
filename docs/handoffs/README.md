# Handoff Protokolü

Bu klasör, İmga.AI projesi üzerinde çalışan üç aktörün arasında structured iletişim için kullanılır:

- **Local Agent:** VS Code'da çalışan, repo'da kod yazan Claude Code
- **Server Agent:** Production sunucu (vdd-prod-1) üzerinde çalışan Claude Code
- **Claude Chat:** Kullanıcının (Hulusi) tartıştığı, plan yapan Claude oturumu (claude.ai web)

## Akış

1. Sorun/görev tanımlandığında handoff dosyası açılır:
   `docs/handoffs/YYYY-MM-DD-<kısa-başlık>.md`

2. INDEX.md'ye yeni satır eklenir.

3. Hedef ajan dosyayı okur, işi yapar, "Cevap" bölümünü doldurur, durum=resolved.

4. Resolved handoff'lar `archive/` altına taşınır (haftada 1).

## Şablon

Her handoff dosyası şu şablonu kullanır:

```markdown
# Handoff: <kısa-başlık>

**Tarih:** YYYY-MM-DD HH:MM
**Sprint:** <sprint-no veya genel>
**Yazar:** local-agent | server-agent | claude-chat
**Hedef:** local-agent | server-agent | claude-chat | user
**Durum:** open | in-progress | blocked | resolved
**Öncelik:** kritik | yüksek | normal | düşük

## Bağlam
(Hangi iş bunu tetikledi)

## Talep
(Hedef ajandan ne isteniyor)

## Mevcut durum
- Yapılanlar
- Yapılmayanlar

## Beklenen çıktı
(Tamamlanma kriterleri)

## İlgili dosyalar / commit'ler
- /path/file
- commit hash

## Cevap
(Hedef ajan doldurur)

---
```

## Kurallar

1. **Tek konu, tek handoff.** Karışık konular ayrı dosya.
2. **Resolved sonrası kapatma.** "Durum: resolved" yaz, commit message: `docs(handoff): resolve <başlık>`.
3. **INDEX.md güncel kalsın.** Açılan/kapanan her handoff INDEX'e yansıtılır.
4. **Commit message formatı:**
   - Yeni handoff: `docs(handoff): open <başlık>`
   - Update: `docs(handoff): update <başlık>`
   - Resolve: `docs(handoff): resolve <başlık>`
5. **Acil durumlar için "Öncelik: kritik"** + commit subject'in başında 🚨 emoji.
