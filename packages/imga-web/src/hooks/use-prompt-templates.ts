// Sprint 9.3 D — admin prompt-templates CRUD + test render.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export interface PromptTemplateRow {
  id: string;
  template_key: string;
  version: string;
  tenant_id: string | null;
  system_prompt: string;
  user_prompt_template: string;
  response_schema: Record<string, unknown>;
  model_name: string;
  temperature: number;
  top_p: number;
  max_output_tokens: number;
  is_active: boolean;
  is_default: boolean;
  required_variables: string[];
  created_at: string;
  updated_at: string;
  is_tenant_override: boolean;
}

export interface PromptTemplateUpsertRequest {
  template_key: string;
  version: string;
  system_prompt: string;
  user_prompt_template: string;
  response_schema?: Record<string, unknown>;
  model_name?: string;
  temperature?: number;
  top_p?: number;
  max_output_tokens?: number;
  required_variables?: string[];
  make_default?: boolean;
}

export interface PromptTemplatePatchRequest {
  system_prompt?: string;
  user_prompt_template?: string;
  response_schema?: Record<string, unknown>;
  model_name?: string;
  temperature?: number;
  top_p?: number;
  max_output_tokens?: number;
  required_variables?: string[];
  is_active?: boolean;
  is_default?: boolean;
}

export interface TestRenderResponse {
  rendered_prompt: string;
  system_prompt: string;
  template_key: string;
  version: string;
  source: "tenant_override" | "global_default";
}

const QUERY_KEY = ["prompt-templates"] as const;

export function usePromptTemplates() {
  return useQuery<PromptTemplateRow[]>({
    queryKey: QUERY_KEY,
    queryFn: () =>
      apiRequest<PromptTemplateRow[]>("/tenants/me/prompt-templates"),
  });
}

export function useCreatePromptOverride() {
  const qc = useQueryClient();
  return useMutation<
    PromptTemplateRow,
    Error,
    PromptTemplateUpsertRequest
  >({
    mutationFn: (body) =>
      apiRequest<PromptTemplateRow>("/tenants/me/prompt-templates", {
        method: "POST",
        body,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function usePatchPromptOverride() {
  const qc = useQueryClient();
  return useMutation<
    PromptTemplateRow,
    Error,
    { id: string; body: PromptTemplatePatchRequest }
  >({
    mutationFn: ({ id, body }) =>
      apiRequest<PromptTemplateRow>(
        `/tenants/me/prompt-templates/${id}`,
        { method: "PATCH", body },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useDeletePromptOverride() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (id) =>
      apiRequest<void>(`/tenants/me/prompt-templates/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useTestRender() {
  return useMutation<
    TestRenderResponse,
    Error,
    { id: string; variables: Record<string, unknown> }
  >({
    mutationFn: ({ id, variables }) =>
      apiRequest<TestRenderResponse>(
        `/tenants/me/prompt-templates/${id}/test`,
        { method: "POST", body: { variables } },
      ),
  });
}
