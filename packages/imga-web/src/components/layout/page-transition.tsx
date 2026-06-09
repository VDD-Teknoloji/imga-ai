"use client";

// Sprint 10.3 — global sayfa giriş animasyonu ("TÜM SAYFALARA").
//
// AppShell'in ana içerik alanını pathname'e key'lenmiş bir
// sarmalayıcıya alır: her rota değişiminde içerik yeniden mount
// olur ve page-enter animasyonu (fade + 10px yükselme, 320ms)
// oynar. Tek dokunuşla bütün sayfalar açılış animasyonu kazanır;
// sayfa-içi mikro animasyonlar (gauge dolması, bar genişlemesi,
// rise-in stagger'ları) bileşenlerin kendindedir.
//
// prefers-reduced-motion globals.css guard'ı ile tek karede biter.

import { usePathname } from "next/navigation";

export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div key={pathname} className="page-enter min-h-full">
      {children}
    </div>
  );
}
