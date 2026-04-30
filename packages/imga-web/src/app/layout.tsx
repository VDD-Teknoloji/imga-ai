import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { Providers } from "@/components/providers";

import "./globals.css";

// Inter is the default until the design palette is finalised. The
// CSS variable name (--font-sans) matches the @theme inline binding
// shadcn already wired up in globals.css, so swapping fonts later
// is a single-import change.
const inter = Inter({
  variable: "--font-sans",
  subsets: ["latin"],
});

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
    <html lang="tr" className={`${inter.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-background text-foreground">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
