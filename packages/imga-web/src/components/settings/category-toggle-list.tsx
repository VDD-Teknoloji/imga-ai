"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useToggleCategory } from "@/hooks/use-tenant-config";
import type { CategoryView } from "@/lib/types";

interface CategoryToggleListProps {
  /** Pass only the global, non-archived categories — custom ones
   * have their own management section. */
  categories: ReadonlyArray<CategoryView>;
}

/**
 * 8-row global-category enable/disable list. Local dirty state
 * tracks pending changes; clicking "Kaydet" fires one PATCH per
 * changed row in parallel and surfaces a single combined toast.
 *
 * Why explicit Save (not auto-save on toggle): rapid-fire toggles
 * during deliberation would each round-trip to the server, and the
 * user has no rollback if they realise mid-flow they want the old
 * mix. Explicit Save keeps the operation atomic from the user's POV.
 */
export function CategoryToggleList({ categories }: CategoryToggleListProps) {
  const toggle = useToggleCategory();
  const [pending, setPending] = useState<Map<string, boolean>>(new Map());
  const [isSaving, setIsSaving] = useState(false);

  // Reset pending edits when the upstream list reference changes (a
  // mutation completed and the snapshot refetched). React 19 prop-
  // tracking pattern instead of useEffect.
  const [lastCategories, setLastCategories] = useState(categories);
  if (lastCategories !== categories) {
    setLastCategories(categories);
    setPending(new Map());
  }

  function effectiveValue(cat: CategoryView): boolean {
    return pending.has(cat.id) ? (pending.get(cat.id) as boolean) : cat.is_enabled;
  }

  function handleToggle(cat: CategoryView, next: boolean) {
    const draft = new Map(pending);
    if (next === cat.is_enabled) {
      draft.delete(cat.id); // back to original — drop the pending entry
    } else {
      draft.set(cat.id, next);
    }
    setPending(draft);
  }

  async function handleSave() {
    if (pending.size === 0) return;
    setIsSaving(true);
    const results = await Promise.allSettled(
      Array.from(pending.entries()).map(([categoryId, isEnabled]) =>
        toggle.mutateAsync({ categoryId, isEnabled }),
      ),
    );
    const failed = results.filter((r) => r.status === "rejected").length;
    setIsSaving(false);
    if (failed === 0) {
      toast.success(`${results.length} kategori güncellendi`);
      setPending(new Map());
    } else {
      toast.error(
        `${failed} / ${results.length} güncelleme başarısız oldu — listeyi yenile.`,
      );
    }
  }

  function handleReset() {
    setPending(new Map());
  }

  const dirtyCount = pending.size;

  return (
    <section className="bg-card space-y-4 rounded-lg border p-6">
      <header className="flex items-baseline justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Global kategoriler</h2>
          <p className="text-muted-foreground text-sm">
            Tenant&apos;ında hangi global kategorilerin kullanılacağını seç. Kapatılan
            kategoriler classifier ve UI&apos;da görünmez.
          </p>
        </div>
      </header>

      <div className="divide-y">
        {categories.map((cat) => {
          const value = effectiveValue(cat);
          const isDirty = pending.has(cat.id);
          return (
            <div key={cat.id} className="flex items-center justify-between py-3">
              <div className="flex flex-col gap-0.5">
                <Label
                  htmlFor={`cat-${cat.id}`}
                  className="cursor-pointer text-sm font-medium"
                >
                  {cat.label_tr}
                  {isDirty ? (
                    <span className="text-muted-foreground ml-2 text-xs font-normal">
                      (kaydedilmedi)
                    </span>
                  ) : null}
                </Label>
                <span className="text-muted-foreground font-mono text-xs">{cat.code}</span>
              </div>
              <Switch
                id={`cat-${cat.id}`}
                checked={value}
                onCheckedChange={(checked) => handleToggle(cat, checked)}
                disabled={isSaving}
                aria-label={`${cat.label_tr}: ${value ? "açık" : "kapalı"}`}
              />
            </div>
          );
        })}
      </div>

      <div className="flex items-center justify-end gap-2">
        {dirtyCount > 0 ? (
          <span className="text-muted-foreground mr-auto text-xs">
            {dirtyCount} bekleyen değişiklik
          </span>
        ) : null}
        <Button variant="ghost" onClick={handleReset} disabled={dirtyCount === 0 || isSaving}>
          Vazgeç
        </Button>
        <Button onClick={handleSave} disabled={dirtyCount === 0 || isSaving}>
          {isSaving ? "Kaydediliyor..." : "Kaydet"}
        </Button>
      </div>
    </section>
  );
}
