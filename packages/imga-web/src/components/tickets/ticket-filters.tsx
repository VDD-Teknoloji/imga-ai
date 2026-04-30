"use client";

import { X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { useCategories } from "@/hooks/use-categories";
import { TICKET_PRIORITY_LABELS } from "@/lib/ticket-actions";
import { TICKET_STATE_LABELS } from "@/lib/ticket-helpers";
import type { TicketPriority, TicketState } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATE_OPTIONS: ReadonlyArray<TicketState> = [
  "open",
  "in_progress",
  "pending_customer",
  "resolved",
  "closed",
  "cancelled",
];

const PRIORITY_OPTIONS: ReadonlyArray<TicketPriority> = ["urgent", "high", "normal", "low"];

const ASSIGNEE_OPTIONS = [
  { value: "me", label: "Bana atananlar" },
  { value: "unassigned", label: "Atanmamış" },
  { value: "any", label: "Herkes" },
] as const;

export type AssigneeFilter = "me" | "unassigned" | "any";

export interface TicketFilterValues {
  states: ReadonlySet<TicketState>;
  priorities: ReadonlySet<TicketPriority>;
  categories: ReadonlySet<string>; // category_ids
  assignee: AssigneeFilter;
}

/**
 * Read filter state from the URL query string. Multi-value filters
 * use comma-separated values (`?state=open,in_progress`) rather than
 * repeated keys — easier to copy/share, easier to read.
 */
export function useTicketFilters(): TicketFilterValues {
  const params = useSearchParams();
  return useMemo(() => {
    const splitCsv = (key: string): Set<string> => {
      const raw = params.get(key);
      if (!raw) return new Set();
      return new Set(raw.split(",").filter(Boolean));
    };
    return {
      states: splitCsv("state") as ReadonlySet<TicketState>,
      priorities: splitCsv("priority") as ReadonlySet<TicketPriority>,
      categories: splitCsv("category"),
      assignee: (params.get("assignee") as AssigneeFilter) ?? "any",
    };
  }, [params]);
}

interface TicketFiltersProps {
  filters: TicketFilterValues;
}

export function TicketFilters({ filters }: TicketFiltersProps) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const categories = useCategories();

  const updateParam = useCallback(
    (key: string, value: string | null) => {
      const next = new URLSearchParams(params.toString());
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  const toggleSetParam = useCallback(
    (key: string, value: string, current: ReadonlySet<string>) => {
      const next = new Set(current);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      updateParam(key, next.size === 0 ? null : Array.from(next).join(","));
    },
    [updateParam],
  );

  const clearAll = useCallback(() => {
    router.replace(pathname, { scroll: false });
  }, [pathname, router]);

  const hasFilters =
    filters.states.size > 0 ||
    filters.priorities.size > 0 ||
    filters.categories.size > 0 ||
    filters.assignee !== "any";

  const categoryOptions = useMemo(
    () =>
      (categories.data ?? [])
        .filter((c) => !c.is_archived)
        .map((c) => ({ id: c.id, label: c.label_tr })),
    [categories.data],
  );

  return (
    <div className="flex flex-wrap items-center gap-2">
      <MultiSelectFilter
        label="Durum"
        active={filters.states}
        options={STATE_OPTIONS.map((s) => ({ id: s, label: TICKET_STATE_LABELS[s] }))}
        onToggle={(v) => toggleSetParam("state", v, filters.states)}
      />
      <MultiSelectFilter
        label="Öncelik"
        active={filters.priorities}
        options={PRIORITY_OPTIONS.map((p) => ({ id: p, label: TICKET_PRIORITY_LABELS[p] }))}
        onToggle={(v) => toggleSetParam("priority", v, filters.priorities)}
      />
      <MultiSelectFilter
        label="Kategori"
        active={filters.categories}
        options={categoryOptions}
        onToggle={(v) => toggleSetParam("category", v, filters.categories)}
      />
      <SingleSelectFilter
        label="Atanan"
        value={filters.assignee}
        options={ASSIGNEE_OPTIONS.map((o) => ({ id: o.value, label: o.label }))}
        onChange={(v) => updateParam("assignee", v === "any" ? null : v)}
      />
      {hasFilters ? (
        <Button variant="ghost" size="sm" onClick={clearAll} className="ml-auto">
          <X className="size-3" aria-hidden />
          Filtreleri temizle
        </Button>
      ) : null}
    </div>
  );
}

interface FilterOption {
  id: string;
  label: string;
}

function MultiSelectFilter({
  label,
  active,
  options,
  onToggle,
}: {
  label: string;
  active: ReadonlySet<string>;
  options: ReadonlyArray<FilterOption>;
  onToggle: (id: string) => void;
}) {
  const count = active.size;
  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button variant="outline" size="sm" className="h-8 gap-2">
            <span>{label}</span>
            {count > 0 ? (
              <Badge variant="secondary" className="h-5 px-1.5">
                {count}
              </Badge>
            ) : null}
          </Button>
        }
      />
      <PopoverContent align="start" className="w-[220px] p-0">
        <Command>
          <CommandInput placeholder={`${label} ara...`} />
          <CommandList>
            <CommandEmpty>Eşleşme yok.</CommandEmpty>
            <CommandGroup>
              {options.map((opt) => {
                const isOn = active.has(opt.id);
                return (
                  <CommandItem
                    key={opt.id}
                    value={opt.label}
                    onSelect={() => onToggle(opt.id)}
                    className="flex items-center gap-2"
                  >
                    <span
                      className={cn(
                        "border-input flex size-4 items-center justify-center rounded-sm border",
                        isOn && "bg-primary border-primary text-primary-foreground",
                      )}
                    >
                      {isOn ? <span className="text-[10px]">✓</span> : null}
                    </span>
                    {opt.label}
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

function SingleSelectFilter({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: ReadonlyArray<FilterOption>;
  onChange: (id: string) => void;
}) {
  const activeOption = options.find((o) => o.id === value);
  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button variant="outline" size="sm" className="h-8 gap-2">
            <span>
              {label}
              {activeOption && value !== "any" ? `: ${activeOption.label}` : ""}
            </span>
          </Button>
        }
      />
      <PopoverContent align="start" className="w-[200px] p-0">
        <Command>
          <CommandList>
            <CommandGroup>
              {options.map((opt) => (
                <CommandItem
                  key={opt.id}
                  value={opt.label}
                  onSelect={() => onChange(opt.id)}
                  className="flex items-center justify-between"
                >
                  <span>{opt.label}</span>
                  {opt.id === value ? <span className="text-primary text-xs">✓</span> : null}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
