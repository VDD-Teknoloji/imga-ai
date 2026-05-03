// Sprint 8.3.5.6 — read-only company-perspective taxonomy.
//
// One query against ``GET /tenants/me/taxonomies``. The 8.3.7 edit UI
// will add mutations; until then the list drives:
//   * /reviews "Şirket Perspektifi" multi-select filter
//   * /insights perspective tab label resolution
//   * Detail page label fallback when the taxonomy row was pruned

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { CategoryTaxonomyView } from "@/lib/types";

export function useCompanyTaxonomies() {
  return useQuery<CategoryTaxonomyView[]>({
    queryKey: ["company-taxonomies"],
    queryFn: () => apiRequest<CategoryTaxonomyView[]>("/tenants/me/taxonomies"),
    // Taxonomy is read-only until 8.3.7 — cache liberally.
    staleTime: 5 * 60 * 1000,
  });
}
