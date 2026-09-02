/**
 * İmga i18n — sözlük birleştirici (Sprint 12).
 *
 * Alan modülleri (`dictionaries/<alan>.ts`) tek tek çevirileri taşır; burada
 * tek bir `dictionaries[locale]` haritasına birleştirilir. Yeni sayfa çevirisi =
 * ilgili alan modülüne anahtar ekle (çakışmasız, alan başına ayrı dosya) +
 * bileşende `t("anahtar")`. Anahtarlar düz string; eksik anahtar çalışma anında
 * tr'ye, sonra anahtar metnine düşer (bkz. use-translation).
 */

import type { Locale } from "./config";
import { admin } from "./dictionaries/admin";
import { analyze } from "./dictionaries/analyze";
import { compare } from "./dictionaries/compare";
import { core } from "./dictionaries/core";
import { dashboard } from "./dictionaries/dashboard";
import { insights } from "./dictionaries/insights";
import { rootCause } from "./dictionaries/root-cause";
import { settings } from "./dictionaries/settings";
import { shell } from "./dictionaries/shell";
import { tickets } from "./dictionaries/tickets";
import type { Bundle } from "./dictionaries/types";

export type MessageKey = string;

const MODULES: readonly Bundle[] = [
  core,
  shell,
  dashboard,
  tickets,
  analyze,
  insights,
  compare,
  settings,
  admin,
  rootCause,
];

function build(locale: Locale): Record<string, string> {
  return Object.assign({}, ...MODULES.map((m) => m[locale]));
}

export const dictionaries: Record<Locale, Record<string, string>> = {
  tr: build("tr"),
  en: build("en"),
};
