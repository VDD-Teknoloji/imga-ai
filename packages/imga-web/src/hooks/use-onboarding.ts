"use client";

// WS1 (2026-08-18) — onboarding: kurum profili genişlemesi (terim
// sözlüğü) + AI kategori önerisi (/tenants/me/onboarding/*).
//
// lib/types.ts'e DOKUNULMADI (görev talimatı) — bu dosya, backend'in
// zaten kabul ettiği ama henüz types.ts'e yansımamış alanları
// (AdminTenantCreateRequest.industry/company_size/business_description/
// terminology, TenantProfile(UpdateRequest).terminology) "gölge tip"
// olarak genişletir: `interface X extends Y { ekstra?: T }` biçimi,
// tüm ekstra alanlar opsiyonel olduğu için TS'in structural typing'i
// bu genişletilmiş tipteki bir DEĞİŞKENİ (fresh literal değil) dar
// tipin beklendiği yere cast'siz geçirmeye izin verir — excess-
// property check yalnız satır-içi literal'lerde tetiklenir.
//
// suggest-categories / apply-categories için ayrı bir mevcut hook
// dosyası yok; response/request şekilleri routes/tenant_onboarding.py
// ile bire bir eşleşecek şekilde burada tanımlanır.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiRequest, ApiError } from "@/lib/api-client";
import type {
  AdminTenantCreateRequest,
  TenantProfile,
  TenantProfileUpdateRequest,
} from "@/lib/types";

// --- terim sözlüğü (tenants.terminology) ---------------------------------

/** Yazma şekli — hem admin create (`list[dict[str,str]]`) hem profile
 *  PATCH (`list[{term, note?}]`) yolunda geçerli: `note` boşsa anahtar
 *  hiç GÖNDERİLMEZ (admin create tarafı `note: null` kabul etmez,
 *  `dict[str, str]` bekler). */
export interface TerminologyEntry {
  term: string;
  note?: string;
}

export const TERMINOLOGY_MAX = 50;

/** GET /tenants/me/profile'ın `terminology` alanı kasten gevşek
 *  (`list[dict[str, Any]] | null`) — eski/admin-create ile yazılmış
 *  şekli bozuk satırlar da olabilir. Editöre hydrate ederken yalnız
 *  `term` alanı dolu-string olan satırlar tutulur, gerisi (ID'siz
 *  anahtar, sayı, vb.) sessizce atlanır — `terminology_directive`'in
 *  gevşek-okuma ilkesiyle aynı disiplin. */
export function normalizeTerminologyForEdit(raw: unknown): TerminologyEntry[] {
  if (!Array.isArray(raw)) return [];
  const out: TerminologyEntry[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const term = record.term;
    if (typeof term !== "string" || term.trim().length === 0) continue;
    const noteRaw = record.note;
    const note =
      typeof noteRaw === "string" && noteRaw.trim().length > 0 ? noteRaw.trim() : undefined;
    // Admin create path never enforced per-field length (plain
    // `list[dict[str,str]]`, no Pydantic max_length) — a legacy row
    // could exceed the profile PATCH's stricter 128/500 caps. Truncate
    // defensively so re-saving from the editor doesn't 422.
    const cleanTerm = term.trim().slice(0, 128);
    out.push(note ? { term: cleanTerm, note: note.slice(0, 500) } : { term: cleanTerm });
  }
  return out;
}

/** Editör state'inden yazma payload'ına: boş `term` satırları elenir,
 *  boş `note` alanı anahtar olarak hiç gönderilmez, liste `max`'a
 *  kırpılır (varsayılan 50 — profile PATCH'in sunucu tavanı; admin
 *  create tarafı 200'e kadar izin verir ama paylaşılan editör tek bir
 *  müşteri deneyimi olarak aynı tavanı kullanır). */
export function sanitizeTerminology(
  entries: TerminologyEntry[],
  max: number = TERMINOLOGY_MAX,
): TerminologyEntry[] {
  const out: TerminologyEntry[] = [];
  for (const entry of entries) {
    const term = entry.term.trim();
    if (!term) continue;
    const note = entry.note?.trim();
    out.push(note ? { term, note } : { term });
    if (out.length >= max) break;
  }
  return out;
}

// --- gölge tipler (types.ts genişletmeleri) -------------------------------

export interface AdminTenantCreateRequestWithProfile extends AdminTenantCreateRequest {
  industry?: string | null;
  industry_other_text?: string | null;
  company_size?: string | null;
  business_description?: string | null;
  terminology?: TerminologyEntry[];
}

export interface TenantProfileWithTerminology extends TenantProfile {
  // Backend şekli kasten gevşek (bkz. normalizeTerminologyForEdit) —
  // burada da aynı gevşeklik korunur, hydrate sırasında normalize edilir.
  terminology?: Array<Record<string, unknown>> | null;
}

export interface TenantProfileUpdateRequestWithTerminology extends TenantProfileUpdateRequest {
  terminology?: TerminologyEntry[];
}

// --- AI kategori önerisi (mirrors routes/tenant_onboarding.py) -----------

export interface SuggestCategoriesRequest {
  sample_limit?: number;
}

export interface SuggestedCategoryView {
  code: string;
  label_tr: string;
  description: string;
}

export interface SuggestedTaxonomyView {
  code: string;
  label_tr: string;
  primary_category_code: string;
}

export interface SuggestCategoriesResponse {
  top_categories: SuggestedCategoryView[];
  subcategories: SuggestedTaxonomyView[];
  disable_global_codes: string[];
  rationale: string;
}

export interface ApplyTopCategoryInput {
  code: string;
  label_tr: string;
  description?: string | null;
}

export interface ApplySubcategoryInput {
  code: string;
  label_tr: string;
  primary_category_code?: string | null;
}

export interface ApplyCategoriesRequest {
  top_categories: ApplyTopCategoryInput[];
  subcategories: ApplySubcategoryInput[];
  disable_global_codes: string[];
}

export interface ApplyCategoriesResponse {
  created_categories: string[];
  created_taxonomies: string[];
  disabled_global_codes: string[];
}

export function useSuggestCategories() {
  return useMutation<SuggestCategoriesResponse, Error, SuggestCategoriesRequest>({
    mutationFn: (body) =>
      apiRequest<SuggestCategoriesResponse>("/tenants/me/onboarding/suggest-categories", {
        method: "POST",
        body,
      }),
  });
}

export function useApplyCategories() {
  const qc = useQueryClient();
  return useMutation<ApplyCategoriesResponse, Error, ApplyCategoriesRequest>({
    mutationFn: (body) =>
      apiRequest<ApplyCategoriesResponse>("/tenants/me/onboarding/apply-categories", {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      // Aynı anahtarlar: hooks/use-taxonomies.ts (["taxonomies"],
      // ["company-taxonomies"]) + hooks/use-categories.ts (["tenant",
      // "categories"]) — apply hem custom kategori/taksonomi yazar hem
      // global toggle'lar, üçü de tazelenmeli.
      qc.invalidateQueries({ queryKey: ["taxonomies"] });
      qc.invalidateQueries({ queryKey: ["company-taxonomies"] });
      qc.invalidateQueries({ queryKey: ["tenant", "categories"] });
    },
  });
}

// --- hata mesajı yardımcıları ---------------------------------------------

/**
 * `apiRequest`, `detail` alanı STRING olmayan gövdeleri (412/503'ün
 * `{code, message}` şekli, 409 `category_code_archived`) "HTTP nnn"e
 * düşürür (bkz. lib/api-client.ts). Buradaki yardımcı ham gövdeyi
 * tekrar açar; bulamazsa `fallback`'e düşer. Çağıran, 412/503 gibi
 * durumlar için genelde sabit bir i18n mesajı tercih eder (bkz.
 * root-cause-dialog.tsx deseni) — bu yalnız 400/409 gibi sunucunun
 * gövdeye gömdüğü Türkçe metnin GERÇEKTEN gösterilmesi gereken
 * durumlar için.
 */
export function apiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const body = err.body;
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string" && detail.length > 0) return detail;
      if (detail && typeof detail === "object" && "message" in detail) {
        const message = (detail as { message: unknown }).message;
        if (typeof message === "string" && message.length > 0) return message;
      }
    }
    if (err.detail && !/^HTTP \d+$/.test(err.detail)) return err.detail;
  }
  return fallback;
}

const CODE_IN_MESSAGE_RE = /['"]([a-z][a-z0-9_]*)['"]/;

/** Servis katmanı hata metinleri kodu Python `!r` (tek tırnak) ile
 *  gömer — ör. `kod 'iade_takip' arşivde mevcut; ...`. Satır-düzeyi
 *  hata gösterimi için hangi öneri satırının çakıştığını çıkarır;
 *  eşleşmezse null (çağıran genel bir banner'a düşer). */
export function extractCodeFromMessage(message: string): string | null {
  const match = CODE_IN_MESSAGE_RE.exec(message);
  return match?.[1] ?? null;
}

// re-export — çağıranlar tek yerden import etsin (types.ts değişmedi).
export type { TenantProfile, TenantProfileUpdateRequest } from "@/lib/types";
