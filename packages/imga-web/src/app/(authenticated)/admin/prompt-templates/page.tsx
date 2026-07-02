"use client";

// Sprint 9.3 D — /admin/prompt-templates editor.
//
// Lists every template visible to the active tenant — global
// defaults + tenant overrides side by side. Selecting a row opens
// an inline editor; "Test" runs the server-side render with a
// user-supplied JSON variables blob.

import { Code2, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  type PromptTemplateRow,
  useCreatePromptOverride,
  useDeletePromptOverride,
  usePatchPromptOverride,
  usePromptCodeDefaults,
  usePromptTemplates,
  useTestRender,
} from "@/hooks/use-prompt-templates";
import { formatApiErrorMessage } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";

// Sprint 11.3 — koda gömülü varsayılanlar listede "sanal satır"
// olarak görünür: DB boşken bile dört üretim şablonu (SWOT, OKR,
// Yönetici Özeti, Yorum Sınıflandırma) kataloglanır; düzenleyip
// kaydedince gerçek tenant override'ına dönüşür.
const CODE_ROW_PREFIX = "code:";

const KEY_TITLE_KEYS: Record<string, string> = {
  swot: "admin.promptTemplates.name.swot",
  okr: "admin.promptTemplates.name.okr",
  briefing: "admin.promptTemplates.name.briefing",
  unified_classifier: "admin.promptTemplates.name.unifiedClassifier",
};

export default function PromptTemplatesPage() {
  const { t } = useTranslation();
  const list = usePromptTemplates();
  const codeDefaults = usePromptCodeDefaults();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // DB satırları + (DB'de hiç görünmeyen anahtarlar için) kod
  // varsayılanlarından türetilen sanal satırlar.
  const dbRows = list.data ?? [];
  const dbKeys = new Set(dbRows.map((row) => row.template_key));
  const virtualRows: PromptTemplateRow[] = (codeDefaults.data ?? [])
    .filter((d) => !dbKeys.has(d.template_key))
    .map((d) => ({
      id: `${CODE_ROW_PREFIX}${d.template_key}`,
      template_key: d.template_key,
      version: "v1",
      tenant_id: null,
      system_prompt: d.system_prompt,
      user_prompt_template: d.user_prompt_template,
      response_schema: d.response_schema,
      model_name: d.model_name,
      temperature: 0.2,
      top_p: 0.9,
      max_output_tokens: 8192,
      is_active: true,
      is_default: true,
      required_variables: d.required_variables,
      created_at: "",
      updated_at: "",
      is_tenant_override: false,
    }));
  const allRows = [...dbRows, ...virtualRows];
  const editableUserPrompt = new Map(
    (codeDefaults.data ?? []).map((d) => [d.template_key, d.user_prompt_editable]),
  );

  const selected = allRows.find((row) => row.id === selectedId);

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6 md:p-8">
      <header className="flex items-start gap-2">
        <Code2 className="text-primary mt-1 size-6" aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
            {t("admin.promptTemplates.title")}
          </h1>
          <p className="text-muted-foreground text-sm">{t("admin.promptTemplates.subtitle")}</p>
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-[260px_1fr]">
        <aside className="bg-card space-y-2 rounded-lg border p-3">
          {list.isLoading ? (
            <div className="flex items-center gap-2 p-3 text-sm">
              <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
            </div>
          ) : list.isError ? (
            <p className="text-destructive text-sm">{t("admin.common.listError")}</p>
          ) : (
            <>
              {codeDefaults.isError && (
                // Code review bulgusu: code-defaults düşerse katalog
                // sessizce boşalıyordu — hatayı görünür kıl, kayıtlı
                // override'lar listelenmeye devam etsin.
                <p className="text-destructive p-2 text-xs">
                  {t("admin.promptTemplates.defaultsError")}
                </p>
              )}
              {allRows.map((row) => {
                const titleKey = KEY_TITLE_KEYS[row.template_key];
                return (
                  <button
                    key={row.id}
                    type="button"
                    onClick={() => setSelectedId(row.id)}
                    className={`block w-full rounded-md p-2 text-left text-sm ${
                      selectedId === row.id
                        ? "bg-primary text-primary-foreground"
                        : "hover:bg-muted"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium">
                        {titleKey ? t(titleKey) : row.template_key}
                      </span>
                      {row.is_tenant_override ? (
                        <Badge className="text-[10px]">
                          {t("admin.promptTemplates.badge.custom")}
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-[10px]">
                          {t("admin.promptTemplates.badge.default")}
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs opacity-70">
                      {row.template_key} · {row.version}
                    </p>
                  </button>
                );
              })}
            </>
          )}
        </aside>

        <section>
          {selected ? (
            // Sprint 9.4 E — ``key`` forces the editor to remount when
            // the operator switches templates. Without it React reuses
            // the same component instance, useState keeps the previous
            // template's edits, and the next save merges form state
            // from template A onto template B's metadata.
            <TemplateEditor
              key={selected.id}
              template={selected}
              isVirtual={selected.id.startsWith(CODE_ROW_PREFIX)}
              userPromptEditable={editableUserPrompt.get(selected.template_key) ?? true}
            />
          ) : (
            <Card>
              <CardContent className="text-muted-foreground p-6 text-center text-sm">
                {t("admin.promptTemplates.selectPrompt")}
              </CardContent>
            </Card>
          )}
        </section>
      </div>
    </main>
  );
}

function TemplateEditor({
  template,
  isVirtual = false,
  userPromptEditable = true,
}: {
  template: PromptTemplateRow;
  /** Kod varsayılanından türeyen sanal satır — DB id'si yok; test
   *  render kapalı, kaydet her zaman yeni override oluşturur. */
  isVirtual?: boolean;
  /** unified_classifier: user prompt yapısını kod kurar — yalnız
   *  system prompt düzenlenebilir. */
  userPromptEditable?: boolean;
}) {
  const { t } = useTranslation();
  const create = useCreatePromptOverride();
  const patch = usePatchPromptOverride();
  const remove = useDeletePromptOverride();
  const testRender = useTestRender();

  const isOverride = template.is_tenant_override;
  const [systemPrompt, setSystemPrompt] = useState(template.system_prompt);
  const [userPrompt, setUserPrompt] = useState(template.user_prompt_template);
  const [varsRaw, setVarsRaw] = useState<string>("{}");
  const [renderResult, setRenderResult] = useState<string | null>(null);

  function onSave() {
    if (isOverride) {
      patch.mutate(
        {
          id: template.id,
          body: {
            system_prompt: systemPrompt,
            user_prompt_template: userPrompt,
          },
        },
        {
          onSuccess: () => toast.success(t("admin.promptTemplates.toast.updated")),
          onError: (err) => toast.error(formatApiErrorMessage(err)),
        },
      );
    } else {
      // Create a tenant override seeded from this global default.
      create.mutate(
        {
          template_key: template.template_key,
          version: `${template.version}-tenant`,
          system_prompt: systemPrompt,
          user_prompt_template: userPrompt,
          response_schema: template.response_schema,
          model_name: template.model_name,
          temperature: template.temperature,
          top_p: template.top_p,
          max_output_tokens: template.max_output_tokens,
          required_variables: template.required_variables,
          make_default: true,
        },
        {
          onSuccess: () => toast.success(t("admin.promptTemplates.toast.created")),
          onError: (err) => toast.error(formatApiErrorMessage(err)),
        },
      );
    }
  }

  function onTestRender() {
    let parsedVars: Record<string, unknown>;
    try {
      parsedVars = JSON.parse(varsRaw);
    } catch {
      toast.error(t("admin.promptTemplates.toast.varsParseError"));
      return;
    }
    testRender.mutate(
      { id: template.id, variables: parsedVars },
      {
        onSuccess: (resp) => {
          setRenderResult(resp.rendered_prompt);
          toast.success(t("admin.promptTemplates.toast.testOk", { source: resp.source }));
        },
        onError: (err) => toast.error(formatApiErrorMessage(err)),
      },
    );
  }

  return (
    <div className="space-y-3">
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="text-sm">{template.template_key}</strong>
            <Badge variant="outline" className="text-xs">
              {template.version}
            </Badge>
            <Badge variant={isOverride ? "default" : "outline"} className="text-xs">
              {isOverride
                ? t("admin.promptTemplates.override")
                : t("admin.promptTemplates.defaultLabel")}
            </Badge>
            <span className="text-muted-foreground ml-auto text-xs">
              {template.model_name} · t={template.temperature}
            </span>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">{t("admin.promptTemplates.systemPrompt")}</Label>
            <Textarea
              rows={4}
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              className="font-mono text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">{t("admin.promptTemplates.userPromptLabel")}</Label>
            <Textarea
              rows={10}
              value={userPrompt}
              onChange={(e) => setUserPrompt(e.target.value)}
              className="font-mono text-xs"
              disabled={!userPromptEditable}
              title={
                userPromptEditable ? undefined : t("admin.promptTemplates.userPromptLockedHint")
              }
            />
          </div>
          {template.required_variables.length > 0 && (
            <p className="text-muted-foreground text-xs">
              {t("admin.promptTemplates.expectedVars")}{" "}
              {template.required_variables.map((v) => (
                <code key={v} className="bg-muted ml-1 rounded px-1">
                  {v}
                </code>
              ))}
            </p>
          )}
          <div className="flex gap-2">
            <Button size="sm" onClick={onSave} disabled={create.isPending || patch.isPending}>
              {isOverride
                ? t("admin.promptTemplates.updateOverride")
                : t("admin.promptTemplates.createOverride")}
            </Button>
            {isOverride && (
              <Button
                size="sm"
                variant="ghost"
                disabled={remove.isPending}
                onClick={() => {
                  if (!confirm(t("admin.promptTemplates.deleteConfirm"))) return;
                  remove.mutate(template.id, {
                    onSuccess: () => toast.success(t("admin.promptTemplates.toast.deleted")),
                    onError: (err) => toast.error(formatApiErrorMessage(err)),
                  });
                }}
                className="text-red-700 hover:text-red-900"
              >
                {t("admin.promptTemplates.deleteOverride")}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 p-4">
          <h3 className="text-sm font-semibold">{t("admin.promptTemplates.testRun")}</h3>
          <div className="space-y-1">
            <Label className="text-xs">{t("admin.promptTemplates.variablesJson")}</Label>
            <Input
              value={varsRaw}
              onChange={(e) => setVarsRaw(e.target.value)}
              className="font-mono text-xs"
              placeholder={t("admin.promptTemplates.varsPlaceholder")}
            />
          </div>
          <Button
            size="sm"
            onClick={onTestRender}
            disabled={isVirtual || testRender.isPending}
            title={isVirtual ? t("admin.promptTemplates.virtualTestHint") : undefined}
          >
            {testRender.isPending
              ? t("admin.promptTemplates.running")
              : t("admin.promptTemplates.testButton")}
          </Button>
          {renderResult !== null && (
            <pre className="bg-muted overflow-x-auto rounded p-3 font-mono text-xs">
              {renderResult}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
