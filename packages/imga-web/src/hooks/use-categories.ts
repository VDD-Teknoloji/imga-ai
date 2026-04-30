"use client";

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { CategoriesResponse, CategoryView } from "@/lib/types";

const CATEGORIES_QUERY_KEY = ["tenant", "categories"] as const;

async function fetchCategories(): Promise<CategoryView[]> {
  const data = await apiRequest<CategoriesResponse>("/tenants/me/categories");
  return data.categories;
}

/** Full list of categories visible to the active tenant (globals + customs). */
export function useCategories() {
  return useQuery({
    queryKey: CATEGORIES_QUERY_KEY,
    queryFn: fetchCategories,
  });
}

/** id → label_tr map, useful for chart legends and ticket-row category badges. */
export function useCategoryLabelMap() {
  return useQuery({
    queryKey: CATEGORIES_QUERY_KEY,
    queryFn: fetchCategories,
    select: (categories): ReadonlyMap<string, string> => {
      const m = new Map<string, string>();
      for (const cat of categories) m.set(cat.id, cat.label_tr);
      return m;
    },
  });
}
