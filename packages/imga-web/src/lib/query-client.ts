// TanStack Query client factory.
//
// Created once per browser tab inside the root layout (useState
// initializer pattern). Defaults are tuned for a B2B dashboard:
// 30s freshness, no refetch-on-focus (quiet UI when alt-tabbing).

import { QueryClient } from "@tanstack/react-query";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30 * 1000,
        gcTime: 5 * 60 * 1000,
        refetchOnWindowFocus: false,
        retry: 1,
      },
      mutations: {
        retry: 0,
      },
    },
  });
}
