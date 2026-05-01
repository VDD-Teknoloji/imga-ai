// Slug helpers for the admin tenant create dialog. Mirrors the
// backend's _SLUG_PATTERN (`^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$`)
// — see imga_api.routes.admin.tenants.

const TURKISH_CHAR_MAP: Record<string, string> = {
  ç: "c",
  ğ: "g",
  ı: "i",
  i̇: "i", // dotted i decomposed
  ö: "o",
  ş: "s",
  ü: "u",
  Ç: "c",
  Ğ: "g",
  İ: "i",
  I: "i",
  Ö: "o",
  Ş: "s",
  Ü: "u",
};

/**
 * Tenant adından otomatik slug üret. Tire ve lowercase ASCII'ye
 * indirger; backend regex'i ile uyumlu.
 *
 *   "Acme Inc."        → "acme-inc"
 *   "Şirket İsmi"      → "sirket-ismi"
 *   "  multi   space"  → "multi-space"
 *   "trailing-"        → "trailing"  (uçtaki tireler kırpılır)
 *   "!@#"              → "" (regex'i geçirmez; UI uyarır)
 */
export function autoSlug(name: string): string {
  let s = name;
  for (const [tr, ascii] of Object.entries(TURKISH_CHAR_MAP)) {
    s = s.split(tr).join(ascii);
  }
  s = s.toLowerCase();
  // Tüm geçersiz karakterleri tireye çevir.
  s = s.replace(/[^a-z0-9]+/g, "-");
  // Çoklu tireleri tek tireye indir.
  s = s.replace(/-+/g, "-");
  // Baş ve sondaki tireleri kırp.
  s = s.replace(/^-+|-+$/g, "");
  return s;
}

export const TENANT_SLUG_PATTERN = /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/;

export function isValidSlug(slug: string): boolean {
  return slug.length >= 1 && slug.length <= 64 && TENANT_SLUG_PATTERN.test(slug);
}
