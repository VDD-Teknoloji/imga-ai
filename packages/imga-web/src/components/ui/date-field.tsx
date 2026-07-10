"use client";

// Sprint 13 — IMGA diline uygun tarih alanı. Native <input type=date>
// korunur (url-state-patterns.md YYYY-MM-DD kuralı + erişilebilirlik),
// ama görünüm Input/SelectTrigger ile aynı aileden: takvim ikonu solda,
// native gösterge görünmez yapılıp tüm alana yayılır — alanın herhangi
// bir yerine tıklamak takvimi açar.

import { CalendarDays } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

type Props = Omit<React.ComponentProps<"input">, "type">;

export function DateField({ className, ...props }: Props) {
  return (
    <div className="relative inline-flex items-center">
      <CalendarDays
        className="text-muted-foreground pointer-events-none absolute left-2.5 z-10 size-3.5"
        aria-hidden
      />
      <input
        type="date"
        {...props}
        className={cn(
          "border-input text-foreground h-8 w-[148px] cursor-pointer rounded-lg border bg-transparent pl-8 pr-2 text-xs tabular-nums transition-colors outline-none",
          "hover:border-primary/50 focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3",
          "dark:bg-input/30 [color-scheme:light] dark:[color-scheme:dark]",
          // Native takvim göstergesini görünmez yapıp tüm alana yay:
          // tık nereye gelirse gelsin picker açılır, ikonumuz solda kalır.
          "[&::-webkit-calendar-picker-indicator]:absolute [&::-webkit-calendar-picker-indicator]:inset-0 [&::-webkit-calendar-picker-indicator]:h-full [&::-webkit-calendar-picker-indicator]:w-full [&::-webkit-calendar-picker-indicator]:cursor-pointer [&::-webkit-calendar-picker-indicator]:opacity-0",
          className,
        )}
      />
    </div>
  );
}
