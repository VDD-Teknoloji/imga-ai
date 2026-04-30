"use client";

import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { CustomCategoryDialog } from "@/components/settings/custom-category-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useArchiveCustomCategory } from "@/hooks/use-tenant-config";
import type { CategoryView } from "@/lib/types";

interface CustomCategoriesSectionProps {
  /** Pass non-global categories. Archived rows are filtered here so
   * they appear in a muted "Arşivlenenler" group beneath the active
   * list — historic ticket views still need to render archived
   * labels even though new tickets cannot reference them. */
  categories: ReadonlyArray<CategoryView>;
}

export function CustomCategoriesSection({ categories }: CustomCategoriesSectionProps) {
  const archive = useArchiveCustomCategory();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<CategoryView | undefined>(undefined);

  const active = categories.filter((c) => !c.is_archived);
  const archived = categories.filter((c) => c.is_archived);

  function openCreate() {
    setEditing(undefined);
    setDialogOpen(true);
  }

  function openEdit(cat: CategoryView) {
    setEditing(cat);
    setDialogOpen(true);
  }

  function handleArchive(cat: CategoryView) {
    if (!window.confirm(`"${cat.label_tr}" kategorisini arşivle?`)) return;
    archive.mutate({ categoryId: cat.id });
  }

  return (
    <section className="bg-card space-y-4 rounded-lg border p-6">
      <header className="flex items-baseline justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Özel kategoriler</h2>
          <p className="text-muted-foreground text-sm">
            Tenant&apos;a özel kategoriler. Kod global kodlarla çakışamaz; arşivlenen
            satırlar geçmiş ticket&apos;larda hâlâ görünür.
          </p>
        </div>
        <Button size="sm" onClick={openCreate}>
          <Plus className="size-4" aria-hidden />
          Yeni
        </Button>
      </header>

      {active.length === 0 ? (
        <p className="text-muted-foreground py-4 text-center text-sm">
          Henüz özel kategori yok.
        </p>
      ) : (
        <ul className="divide-y">
          {active.map((cat) => (
            <li key={cat.id} className="flex items-start justify-between gap-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-medium">{cat.label_tr}</span>
                  <span className="text-muted-foreground font-mono text-xs">{cat.code}</span>
                  {!cat.is_enabled ? (
                    <Badge variant="secondary" className="text-xs">
                      kapalı
                    </Badge>
                  ) : null}
                </div>
                {cat.description ? (
                  <p className="text-muted-foreground mt-1 text-xs">{cat.description}</p>
                ) : null}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Düzenle"
                  onClick={() => openEdit(cat)}
                  disabled={archive.isPending}
                >
                  <Pencil className="size-4" aria-hidden />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Arşivle"
                  onClick={() => handleArchive(cat)}
                  disabled={archive.isPending}
                  className="text-destructive hover:text-destructive"
                >
                  <Trash2 className="size-4" aria-hidden />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {archived.length > 0 ? (
        <div className="border-border space-y-2 border-t pt-4">
          <h3 className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
            Arşivlenenler ({archived.length})
          </h3>
          <ul className="divide-y opacity-60">
            {archived.map((cat) => (
              <li key={cat.id} className="flex items-baseline gap-2 py-2">
                <span className="text-sm">{cat.label_tr}</span>
                <span className="text-muted-foreground font-mono text-xs">{cat.code}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <CustomCategoryDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        category={editing}
      />
    </section>
  );
}
