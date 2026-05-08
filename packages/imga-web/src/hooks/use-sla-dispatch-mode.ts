// Sprint 9.0.5-B C — SLA webhook dispatch-mode hook.
//
// Backs the toggle on /settings/sla-rules. Reads + writes
// /tenants/me/pending-webhooks/dispatch-mode (endpoints shipped in
// Sprint 9.0 D-backend; the toggle UI is what 9.0.5-B closes).
//
// The mode is binary: ``automatic`` (live httpx.post on every SLA
// breach — default) vs ``manual`` (queued in pending_webhook_events
// for the operator to dispatch from /pending-webhooks). Switching to
// ``manual`` is operator-visible: existing in-flight breaches keep
// flowing live until the next breach lands; once a row arrives in
// the manual queue, it stays until the operator dispatches or
// cancels.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export type SlaDispatchMode = "automatic" | "manual";

interface DispatchModeResponse {
  sla_webhook_dispatch_mode: SlaDispatchMode;
}

export function useSlaDispatchMode() {
  return useQuery<DispatchModeResponse>({
    queryKey: ["sla-dispatch-mode"],
    queryFn: async () =>
      apiRequest<DispatchModeResponse>(
        "/tenants/me/pending-webhooks/dispatch-mode",
      ),
  });
}

export function useUpdateSlaDispatchMode() {
  const queryClient = useQueryClient();
  return useMutation<DispatchModeResponse, Error, SlaDispatchMode>({
    mutationFn: async (mode) =>
      apiRequest<DispatchModeResponse>(
        "/tenants/me/pending-webhooks/dispatch-mode",
        {
          method: "PATCH",
          // apiRequest wrapper auto-serialises JSON + sets the
          // Content-Type header; passing the raw object is the
          // canonical pattern (see other PATCH call sites).
          body: { sla_webhook_dispatch_mode: mode },
        },
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(["sla-dispatch-mode"], data);
      queryClient.invalidateQueries({ queryKey: ["pending-webhooks"] });
    },
  });
}
