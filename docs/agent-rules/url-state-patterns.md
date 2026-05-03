# URL State Patterns — Kalıcı Kural Seti

**Status:** Active rule. Apply on EVERY new page/feature that has filterable, tab-able, paginatable, or otherwise navigable state.

**Last updated:** 2026-05-04 (Sprint 8.3.5.6 round-2)

**Scope:** `packages/imga-web` — Next.js 16 + React 19, App Router.

## Kural

Aşağıdaki state türleri URL search params'ında tutulmak ZORUNDA:

- **Tab seçimi** — örn. `/insights?tab=nps`
- **Filter seçimi** — örn. `/reviews?perspective_codes=shipment_not_arrived,store_issues`
- **Pagination / offset** — sayfa state'i URL'de
- **Sort order** — kolon + yön
- **Date range** — `date_from`, `date_to` (YYYY-MM-DD, ISO datetime DEĞİL — `use-analytics.ts` 1 günlük timezone slide deneyimini hatırla)
- **Search query** — `?search=...`

Bu state'ler:

- F5 sonrası **korunmalı**
- **Paylaşılabilir URL** üretmeli (kopyala-yapıştır aynı görünümü açar)
- Browser **back/forward** navigation'a duyarlı olmalı
- Deep-link'lenebilir olmalı (örn. `/insights` heatmap'inden `/reviews?sentiment_labels=NEGATIF&category=kargo` 'ya tıklama)

## Pattern: Suspense wrapper + Path B mirror (zorunlu)

Sprint 8.3.4 round-1 → round-2 öğrenme zinciri:

- **Round-1** (saf URL-as-truth, useMemo([searchParams])): Hard refresh + non-empty query → tab clicks `onValueChange` ateşliyor, handler URL push ediyor, ama Suspense child'ında `useSearchParams` ilk hidration'dan sonra subscriber notification göndermiyor → controlled `<Tabs value={tab}>` prop'u güncellenmiyor → UI donuyor.
- **Round-2** (mirror pattern): Local `useState` controlled primitive'lere immediate güncelleme verir, `router.push` URL'i kayıt eder, `useEffect([searchParams])` external nav (back/forward, deep-link) için URL → state senkronizasyonu sağlar.
- **Sprint 8.3.5.6 round-2** (bu fix): `/reviews` Suspense'siz `useSearchParams` kullanıyordu ve filter F5 sonrası persist etmedi. Kural: Suspense wrapper + Path B mirror her ikisi her zaman birlikte gerek.

### İskelet — kopya-yapıştır referans

```tsx
"use client";

import { Suspense, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

// 1) Page COMPONENT WRAPPER — Suspense zorunlu.
// useSearchParams Next.js 16'da Suspense bekler; aksi halde build
// uyarısı ve hidration race riski.
export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <PageInner />
    </Suspense>
  );
}

function PageSkeleton() {
  return <main className="..."><p>Yükleniyor…</p></main>;
}

// 2) Inner component — useSearchParams burada çağrılır.
function PageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // 3) URL → local state mirror (lazy initial: hidration sonrası
  // hemen URL ile sync; sonraki güncellemeler aşağıdaki useEffect ile).
  const [selectedPerspectives, setSelectedPerspectives] = useState<string[]>(
    () => searchParams.get("perspective_codes")?.split(",").filter(Boolean) ?? [],
  );

  // 4) URL → state mirror useEffect — back/forward, deep-link, F5
  // hidration race olduğunda local state'i URL ile yeniden hizala.
  // Functional setter formu: değişmediyse referans aynı kalır,
  // gereksiz re-render olmaz.
  useEffect(() => {
    const fromUrl = searchParams.get("perspective_codes")?.split(",").filter(Boolean) ?? [];
    setSelectedPerspectives((prev) =>
      prev.length === fromUrl.length && prev.every((v, i) => v === fromUrl[i])
        ? prev
        : fromUrl,
    );
    // eslint-disable-next-line react-hooks/set-state-in-effect
    // INTENT: URL is source of truth; mirror onto local state on
    // navigation events. Path B pattern (Sprint 8.3.4 round-2).
  }, [searchParams]);

  // 5) State change → URL update (kullanıcı action'ı)
  function handleChange(next: string[]) {
    setSelectedPerspectives(next); // immediate UI update
    const params = new URLSearchParams(searchParams.toString());
    if (next.length === 0) params.delete("perspective_codes");
    else params.set("perspective_codes", next.join(","));
    const qs = params.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  // 6) Data fetch — local state'i kullan (URL hidration race olabilir).
  const { data } = useReviews({ perspective_codes: selectedPerspectives });

  return <FilterDropdown value={selectedPerspectives} onChange={handleChange} />;
}
```

### Önemli detaylar

- **Lazy initial state** (`useState(() => ...)`): Component mount'ta searchParams snapshot'ını synchronously okur. Sonraki güncellemeler useEffect ile gelir.
- **Functional setter karşılaştırma**: `setX((prev) => deepEqual(prev, fromUrl) ? prev : fromUrl)` — referans değişmemesi gereksiz fetch'leri önler (TanStack Query queryKey deps'i bu referansı izliyorsa).
- **`router.push` vs `router.replace`**: Filter seçiminde `push` (history entry oluştur, back button geri getirir). Tab değişiminde de `push` (paylaşılabilir URL). Sadece "form input typing" gibi yüksek-frekans güncellemelerde `replace` kullanılır (history kirlenmesin).
- **`{ scroll: false }`**: Filter güncellemesinde sayfa başına atlamayı engellemek için zorunlu.
- **Date string formatı**: `YYYY-MM-DD` (native `<input type="date">`'in ürettiği). ISO datetime'a expand etmek için fetch hook'unda `dateOnlyToLocalIso` helper'ı (use-analytics.ts'deki gibi) kullan — burada değil.

## Yasaklar

❌ **YAPMA:** `useSearchParams` kullanan bir page component'i Suspense wrapper'sız bırakmak.
❌ **YAPMA:** Sadece `useState` ile filter state — URL'e yansımaz, paylaşılamaz.
❌ **YAPMA:** Saf URL-as-truth (`useMemo([searchParams])` only) Suspense child'ında — round-1 freeze.
❌ **YAPMA:** State mirror'da `JSON.stringify` deep-eq: küçük arrays için over-engineering, `length === length && every === every` yeterli.
❌ **YAPMA:** Filter değişiminde `scroll: false` parametresini unutmak — UX bozulur.
❌ **YAPMA:** `router.refresh()` filter değişiminde — server component'leri yeniden fetch eder, `router.push` zaten URL'i günceller.

## Self-check checklist (component yazarken)

```text
[ ] Page component Suspense ile wrap edildi mi (`<Suspense fallback>`)?
[ ] Inner component useSearchParams kullanıyor mu?
[ ] Lazy initial state (useState(() => ...)) URL'den hidrate ediyor mu?
[ ] useEffect ile URL → state mirror var mı (F5/back/forward için)?
[ ] eslint-disable-next-line + INTENT yorumu (set-state-in-effect kuralını bilinçli geçiyoruz)?
[ ] User action'da: önce setState (immediate UI), sonra router.push (URL kaydet)?
[ ] router.push çağrısında { scroll: false }?
[ ] Data fetch local state'i kullanıyor mu, searchParams.get() değil?
```

## Browser smoke test (zorunlu)

Filter eklediğin her sayfada manuel olarak:

1. Filter aç → URL'de query param görünüyor mu?
2. **F5 → filter durumu korunuyor mu?**
3. Browser **back button** → bir önceki filter durumu geri geliyor mu?
4. URL'i kopyala-yapıştır (yeni tab) → aynı filter durumu açılıyor mu?
5. Filter'ı temizle → URL'den param kayboluyor mu?

Lokal dev server kalkmıyorsa production smoke ile yap. **F5 testini ATLAMA** — round-1/round-2 zinciri tamamen bu testin atlanmasından çıktı.

## Olay tarihçesi (neden bu kural var)

- **Sprint 8.3.4 round-1**: `/insights` filter F5 sonrası kayboluyor → round-2 fix
- **Sprint 8.3.4 round-2**: Path B mirror pattern oturdu — `/insights` doğru çalışıyor
- **Sprint 8.3.5.6**: `/reviews` filter eklendi — Path B uygulanmadı → F5 sonrası filter kayboldu → round-2 fix (bu commit zinciri)

Pattern uygulanmadığında her sprint round-2 maliyeti çıkarıyor. Kuralı dosyalaştırıp `CLAUDE.md` linkleriyle gelecek session'lara aktarıyoruz.

## Mevcut sayfaların durumu (2026-05-04 audit)

| Sayfa | Suspense | Path B | URL filter'lar | F5 davranışı |
| --- | --- | --- | --- | --- |
| `/insights` | ✅ | ✅ | tab, date_from, date_to, source_types | ✅ doğrulandı (Sprint 8.3.4 round-2) |
| `/reviews` | ✅ | ✅ | sentiment_labels, source_types, perspective_codes, has_ticket, batch_job_id, search | ✅ Sprint 8.3.5.6 round-2 |
| `/tickets` | ❌ yok | ❌ yok (saf `useSearchParams + useMemo`) | state, priority, category, assignee | ⚠️ kullanıcı bug rapor etmedi ama F5 davranışı doğrulanmadı; Path B refactor sıraya alındı (Sprint 8.3.6 polish — `useTicketFilters` hook + `TicketFilters` component + page üçünü birden gerektirir, scope creep olduğu için 8.3.5.6 round-2'de dokunulmadı) |
| `/reports` | n/a | n/a | URL filter yok | n/a; `pollingId` ephemeral mutation state (URL'e koymak isteğe bağlı) |
| `/analyze/upload` | n/a | n/a | URL filter yok (multi-step in-memory wizard) | `activeJobId` URL'de değil — refresh'te progress kayıp; ayrı kategori, gelecek sprint'te ele alınabilir |

### `/insights` sub-state notu

NPS tab'ında `months_back` (12 hardcoded) ve Perspective tab'ında `top_n`
(10 hardcoded) UI değişkeni yok — slider/select eklendiğinde URL'e
bağlanması gerek. Şu an URL'e koymak için önce UI kontrolü ekleme
şartı var; scope creep olarak Sprint 8.3.6+ polish.

## URL'de TUTULMAYACAK state örnekleri

URL'in her şeyi taşıması gerekmiyor. Şunlar ephemeral kalır:

- **Modal açık/kapalı** — modal'a deep-link gerekmedikçe (örn. `/reports?modal=create` → URL'e koyabilirsin, ama varsayılan değil)
- **Form draft input'ları** — kullanıcı yazıyor, URL her keystroke'ta güncellenmez
- **Hover/focus state** — pure UI ephemeral
- **In-progress mutation state** — örn. `pollingId` — ayrı kategori (URL'e koymak isteğe bağlı, scope creep)
- **Component-internal expand/collapse** — accordion vb. (eğer "view preference" değilse)

Ama tab/filter/sort/page/search → her zaman URL.
