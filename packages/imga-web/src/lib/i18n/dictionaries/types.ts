/** Bir alan sözlüğü: aynı anahtar kümesinin tr + en çevirileri. */
export interface Bundle {
  tr: Record<string, string>;
  en: Record<string, string>;
}
