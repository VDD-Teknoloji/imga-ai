import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata } from "next";

import { LocaleHtmlLang } from "@/components/i18n/locale-html-lang";
import { Providers } from "@/components/providers";

import "./globals.css";

// Geist Sans + Geist Mono via the official `geist` package. Both
// expose `.variable` strings ready to drop on <html>; globals.css
// binds --font-sans / --font-mono in @theme inline so Tailwind
// utilities (font-sans, font-mono) resolve through these CSS vars
// without further config. The Geist family ships full Latin coverage
// including Turkish glyphs (İ, ı, ç, ş, ğ, ü, ö).

export const metadata: Metadata = {
  title: "imga.ai",
  description: "Türkçe yorum analizi ve ticket yönetimi.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="tr" className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}>
      <body className="bg-background text-foreground flex min-h-full flex-col">
        <Providers>
          <LocaleHtmlLang />
          {children}
        </Providers>
      </body>
    </html>
  );
}
