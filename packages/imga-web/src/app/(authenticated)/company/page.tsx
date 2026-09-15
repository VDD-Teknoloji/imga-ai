"use client";

import { Suspense, useEffect, useState } from "react";
import { Check, Plus, Save, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DocumentHistory } from "@/components/intelligence/document-history";
import { Choice, ErrorMessage, Field, Loading, Workspace } from "@/components/intelligence/fields";
import {
  useIntelligenceQuery,
  useIntelligenceTenant,
  useIntelligenceUrl,
  useSaveDocument,
} from "@/hooks/use-intelligence";
import { useRoleFlags } from "@/hooks/use-role-flags";
import { useTranslation } from "@/lib/i18n/use-translation";
import type {
  CompanyContext,
  CompanyDiagnostics,
  CompanyProcess,
  DocumentSnapshot,
  OrgUnit,
} from "@/lib/intelligence-types";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <CompanyLoader />
    </Suspense>
  );
}
function CompanyLoader() {
  const tenant = useIntelligenceTenant();
  const query = useIntelligenceQuery<DocumentSnapshot<CompanyContext>>("/documents/company");
  if (query.isLoading) return <Loading />;
  if (!query.data) return <ErrorMessage error={query.error} />;
  return <CompanyEditor key={tenant} initial={query.data} />;
}
function CompanyEditor({ initial }: { initial: DocumentSnapshot<CompanyContext> }) {
  const { t } = useTranslation();
  const { canWrite, isAdmin } = useRoleFlags();
  const { params, change } = useIntelligenceUrl();
  const tabs = ["general", "organization", "processes", "diagnostics", "history"];
  const tab = tabs.includes(params.get("tab") ?? "") ? params.get("tab")! : "general";
  const [snapshot, setSnapshot] = useState(initial);
  const [draft, setDraft] = useState(initial.content);
  const [error, setError] = useState<unknown>(null);
  const save = useSaveDocument<CompanyContext>("company");
  const latest = useIntelligenceQuery<DocumentSnapshot<CompanyContext>>("/documents/company");
  const dirty = JSON.stringify(draft) !== JSON.stringify(snapshot.content);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function patch(values: Partial<CompanyContext>) {
    setDraft({ ...draft, ...values });
  }
  function unitPatch(id: string, values: Partial<OrgUnit>) {
    patch({ units: draft.units.map((unit) => (unit.id === id ? { ...unit, ...values } : unit)) });
  }
  function processPatch(id: string, values: Partial<CompanyProcess>) {
    patch({
      processes: draft.processes.map((process) =>
        process.id === id ? { ...process, ...values } : process,
      ),
    });
  }
  async function persist(status: "draft" | "approved") {
    setError(null);
    try {
      const result = await save.mutateAsync({
        content: { ...draft, processes: draft.processes.map((process) => ({
          ...process, category_codes: Array.from(new Set(process.category_codes.map((code) => code.trim()).filter(Boolean))),
        })) },
        expected_revision: snapshot.revision,
        status,
      });
      setSnapshot(result);
      setDraft(result.content);
    } catch (cause) {
      setError(cause);
    }
  }
  const unitOptions = [
    { value: "", label: t("intel.none") },
    ...draft.units.map((unit) => ({ value: unit.id, label: unit.name })),
  ];
  function removeUnit(id: string) {
    if (!window.confirm(t("intel.remove") + "?")) return;
    patch({
      units: draft.units
        .filter((unit) => unit.id !== id)
        .map((unit) => (unit.parent_id === id ? { ...unit, parent_id: null } : unit)),
      processes: draft.processes.map((process) => ({
        ...process,
        owner_unit_id: process.owner_unit_id === id ? null : process.owner_unit_id,
        steps: process.steps.map((step) => ({
          ...step,
          owner_unit_id: step.owner_unit_id === id ? null : step.owner_unit_id,
        })),
      })),
    });
  }
  return (
    <Workspace
      title={t("intel.company")}
      actions={
        <>
          {canWrite && (
            <Button disabled={save.isPending} onClick={() => persist("draft")}>
              <Save />
              {t("intel.save")}
            </Button>
          )}
          {isAdmin && (
            <Button variant="outline" disabled={save.isPending} onClick={() => persist("approved")}>
              <Check />
              {t("intel.publish")}
            </Button>
          )}
        </>
      }
    >
      <ErrorMessage error={error} />
      <div className="text-muted-foreground flex flex-wrap items-center gap-3 text-sm">
        <span>
          {t("intel.revision")} {snapshot.revision} · {t(`intel.${snapshot.status}`)}
        </span>
        <span>{dirty ? t("intel.unsaved") : t("intel.saved")}</span>
        {!canWrite && <span>{t("intel.readOnly")}</span>}
        {latest.data && latest.data.revision !== snapshot.revision && (
          <Button
            variant="outline"
            onClick={() => {
              if (!dirty || window.confirm(t("intel.discard"))) {
                setSnapshot(latest.data);
                setDraft(latest.data.content);
              }
            }}
          >
            {t("intel.reload")}
          </Button>
        )}
      </div>
      <div role="tablist" aria-label={t("intel.company")} className="flex flex-wrap gap-1 border-b">
        {tabs.map((key) => (
          <button
            role="tab"
            aria-selected={key === tab}
            aria-controls="company-panel"
            id={`tab-${key}`}
            className={`border-b-2 px-3 py-2 text-sm ${key === tab ? "border-foreground font-medium" : "text-muted-foreground border-transparent"}`}
            key={key}
            onClick={() => change({ tab: key })}
          >
            {t(`intel.${key}`)}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="company-panel" aria-labelledby={`tab-${tab}`}>
        {tab === "history" ? (
          <DocumentHistory<CompanyContext>
            kind="company"
            render={(content) => (
              <>
                <h2 className="font-medium">{content.name}</h2>
                <p dir="auto">{content.purpose}</p>
                <p>
                  {content.analysis_profile} · {content.report_language} · {content.timezone}
                </p>
                <h3>{t("intel.organization")}</h3>
                {content.units.map((unit) => (
                  <p key={unit.id}>
                    {unit.name} ({unit.id}) · {unit.accountable_role} · {unit.parent_id}
                  </p>
                ))}
                <h3>{t("intel.processes")}</h3>
                {content.processes.map((process) => (
                  <div key={process.id} className="space-y-1 border-b pb-2">
                    <h4 className="font-medium">
                      {process.name} ({process.id})
                    </h4>
                    <p>
                      {process.category_codes.join(", ")} · {process.resolution_target_minutes} min
                      · {process.owner_unit_id}
                    </p>
                    <p>
                      {process.source} · {process.verified_on}
                    </p>
                    <ol className="list-inside list-decimal">
                      {process.steps.map((step, i) => (
                        <li key={i}>
                          {step.name} · {step.owner_unit_id} · {step.target_minutes} min
                        </li>
                      ))}
                    </ol>
                  </div>
                ))}
              </>
            )}
          />
        ) : tab === "diagnostics" ? (
          <Diagnostics />
        ) : (
          <fieldset disabled={!canWrite || save.isPending} className="space-y-6">
            {tab === "general" && (
              <div className="grid gap-5 md:grid-cols-2">
                <Field
                  label={t("intel.name")}
                  value={draft.name}
                  maxLength={160}
                  onChange={(name) => patch({ name })}
                />
                <Choice
                  label={t("intel.timezone")}
                  value={draft.timezone}
                  options={Array.from(
                    new Set([
                      draft.timezone,
                      "Asia/Riyadh",
                      "Asia/Dubai",
                      "Europe/Istanbul",
                      "UTC",
                    ]),
                  ).map((value) => ({ value, label: value }))}
                  onChange={(timezone) => patch({ timezone })}
                />
                <Field
                  label={t("intel.purpose")}
                  value={draft.purpose}
                  multiline
                  onChange={(purpose) => patch({ purpose })}
                />
                <Field
                  label={t("intel.businessModel")}
                  value={draft.business_model}
                  maxLength={1000}
                  multiline
                  onChange={(business_model) => patch({ business_model })}
                />
                <Choice
                  label={t("intel.profile")}
                  value={draft.analysis_profile}
                  options={[
                    { value: "tr", label: t("intel.trProfile") },
                    { value: "mena", label: t("intel.menaProfile") },
                  ]}
                  onChange={(value) =>
                    patch({ analysis_profile: value as CompanyContext["analysis_profile"] })
                  }
                />
                <Choice
                  label={t("intel.reportLanguage")}
                  value={draft.report_language}
                  options={[
                    { value: "tr", label: "Türkçe" },
                    { value: "en", label: "English" },
                    { value: "ar", label: "العربية" },
                    { value: "ur", label: "اردو" },
                  ]}
                  onChange={(value) =>
                    patch({ report_language: value as CompanyContext["report_language"] })
                  }
                />
                <div className="space-y-2">
                  <h2 className="text-sm font-medium">{t("intel.markets")}</h2>
                  <div className="flex flex-wrap gap-4">
                    {[
                      { code: "SA", name: "Saudi Arabia" },
                      { code: "AE", name: "United Arab Emirates" },
                      { code: "TR", name: "Türkiye" },
                      { code: "other", name: "Other" },
                    ].map((market) => (
                      <label key={market.code} className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={draft.markets.includes(market.code)}
                          onChange={(event) =>
                            patch({
                              markets: event.target.checked
                                ? [...draft.markets, market.code]
                                : draft.markets.filter((code) => code !== market.code),
                            })
                          }
                        />
                        {market.name}
                      </label>
                    ))}
                  </div>
                </div>
                <Field
                  label={t("intel.constraints")}
                  value={draft.constraints}
                  multiline
                  onChange={(constraints) => patch({ constraints })}
                />
              </div>
            )}
            {tab === "organization" && (
              <>
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-medium">
                    {t("intel.organization")} ({draft.units.length})
                  </h2>
                  <Button
                    variant="outline"
                    disabled={draft.units.length >= 100}
                    onClick={() =>
                      patch({
                        units: [
                          ...draft.units,
                          {
                            id: `unit_${crypto.randomUUID().slice(0, 8)}`,
                            name: t("intel.newUnit"),
                            parent_id: null,
                            accountable_role: "",
                            mandate: "",
                          },
                        ],
                      })
                    }
                  >
                    <Plus />
                    {t("intel.addUnit")}
                  </Button>
                </div>
                {!draft.units.length && (
                  <p className="text-muted-foreground text-sm">{t("intel.empty")}</p>
                )}
                {draft.units.map((unit) => (
                  <section key={unit.id} className="space-y-4 border-b pb-5">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-medium break-words">{unit.id}</h3>
                      <Button
                        size="icon"
                        variant="ghost"
                        title={t("intel.remove")}
                        aria-label={t("intel.remove")}
                        onClick={() => removeUnit(unit.id)}
                      >
                        <Trash2 />
                      </Button>
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <Field
                        label={t("intel.unit")}
                        value={unit.name}
                        maxLength={160}
                        onChange={(name) => unitPatch(unit.id, { name })}
                      />
                      <Choice
                        label={t("intel.parent")}
                        value={unit.parent_id ?? ""}
                        options={unitOptions.filter((option) => option.value !== unit.id)}
                        onChange={(parent_id) =>
                          unitPatch(unit.id, { parent_id: parent_id || null })
                        }
                      />
                      <Field
                        label={t("intel.accountableRole")}
                        value={unit.accountable_role}
                        maxLength={160}
                        onChange={(accountable_role) => unitPatch(unit.id, { accountable_role })}
                      />
                      <Field
                        label={t("intel.mandate")}
                        value={unit.mandate}
                        maxLength={1000}
                        multiline
                        onChange={(mandate) => unitPatch(unit.id, { mandate })}
                      />
                    </div>
                  </section>
                ))}
              </>
            )}
            {tab === "processes" && (
              <>
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-medium">
                    {t("intel.processes")} ({draft.processes.length})
                  </h2>
                  <Button
                    variant="outline"
                    disabled={draft.processes.length >= 100}
                    onClick={() =>
                      patch({
                        processes: [
                          ...draft.processes,
                          {
                            id: `process_${crypto.randomUUID().slice(0, 8)}`,
                            name: t("intel.newProcess"),
                            owner_unit_id: null,
                            category_codes: [],
                            steps: [],
                            resolution_target_minutes: null,
                            escalation: "",
                            source: "",
                            verified_on: null,
                          },
                        ],
                      })
                    }
                  >
                    <Plus />
                    {t("intel.addProcess")}
                  </Button>
                </div>
                {!draft.processes.length && (
                  <p className="text-muted-foreground text-sm">{t("intel.empty")}</p>
                )}
                {draft.processes.map((process) => (
                  <section key={process.id} className="space-y-4 border-b pb-6">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-medium">{process.id}</h3>
                      <Button
                        size="icon"
                        variant="ghost"
                        title={t("intel.remove")}
                        aria-label={t("intel.remove")}
                        onClick={() => {
                          if (window.confirm(t("intel.remove") + "?"))
                            patch({
                              processes: draft.processes.filter((item) => item.id !== process.id),
                            });
                        }}
                      >
                        <Trash2 />
                      </Button>
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <Field
                        label={t("intel.process")}
                        value={process.name}
                        maxLength={160}
                        onChange={(name) => processPatch(process.id, { name })}
                      />
                      <Choice
                        label={t("intel.owner")}
                        value={process.owner_unit_id ?? ""}
                        options={unitOptions}
                        onChange={(owner_unit_id) =>
                          processPatch(process.id, { owner_unit_id: owner_unit_id || null })
                        }
                      />
                      <Field
                        label={t("intel.categories")}
                        value={process.category_codes.join(",")}
                        maxLength={2000}
                        onChange={(value) =>
                          processPatch(process.id, { category_codes: value.split(",") })
                        }
                      />
                      <Field
                        label={t("intel.target")}
                        type="number"
                        value={process.resolution_target_minutes}
                        onChange={(value) =>
                          processPatch(process.id, {
                            resolution_target_minutes: value === "" ? null : Number(value),
                          })
                        }
                      />
                      <Field
                        label={t("intel.escalation")}
                        value={process.escalation}
                        maxLength={1000}
                        multiline
                        onChange={(escalation) => processPatch(process.id, { escalation })}
                      />
                      <Field
                        label={t("intel.source")}
                        value={process.source}
                        maxLength={500}
                        multiline
                        onChange={(source) => processPatch(process.id, { source })}
                      />
                      <Field
                        label={t("intel.verifiedOn")}
                        type="date"
                        value={process.verified_on}
                        onChange={(verified_on) =>
                          processPatch(process.id, { verified_on: verified_on || null })
                        }
                      />
                    </div>
                    <div className="space-y-3">
                      <h4 className="text-sm font-medium">{t("intel.steps")}</h4>
                      {process.steps.map((step, index) => (
                        <div
                          key={index}
                          className="grid items-end gap-3 border-l-2 pl-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_120px_36px]"
                        >
                          <Field
                            label={`${index + 1}. ${t("intel.name")}`}
                            value={step.name}
                            maxLength={160}
                            onChange={(name) =>
                              processPatch(process.id, {
                                steps: process.steps.map((value, i) =>
                                  i === index ? { ...value, name } : value,
                                ),
                              })
                            }
                          />
                          <Choice
                            label={t("intel.owner")}
                            value={step.owner_unit_id ?? ""}
                            options={unitOptions}
                            onChange={(owner_unit_id) =>
                              processPatch(process.id, {
                                steps: process.steps.map((value, i) =>
                                  i === index
                                    ? { ...value, owner_unit_id: owner_unit_id || null }
                                    : value,
                                ),
                              })
                            }
                          />
                          <Field
                            label={t("intel.stepTarget")}
                            type="number"
                            value={step.target_minutes}
                            onChange={(raw) =>
                              processPatch(process.id, {
                                steps: process.steps.map((value, i) =>
                                  i === index
                                    ? { ...value, target_minutes: raw === "" ? null : Number(raw) }
                                    : value,
                                ),
                              })
                            }
                          />
                          <Button
                            size="icon"
                            variant="ghost"
                            title={t("intel.remove")}
                            aria-label={t("intel.remove")}
                            onClick={() =>
                              processPatch(process.id, {
                                steps: process.steps.filter((_, i) => i !== index),
                              })
                            }
                          >
                            <Trash2 />
                          </Button>
                        </div>
                      ))}
                      <Button
                        variant="outline"
                        disabled={process.steps.length >= 30}
                        onClick={() =>
                          processPatch(process.id, {
                            steps: [
                              ...process.steps,
                              {
                                name: t("intel.newStep"),
                                owner_unit_id: process.owner_unit_id,
                                target_minutes: null,
                              },
                            ],
                          })
                        }
                      >
                        <Plus />
                        {t("intel.addStep")}
                      </Button>
                    </div>
                  </section>
                ))}
              </>
            )}
          </fieldset>
        )}
      </div>
    </Workspace>
  );
}
function Diagnostics() {
  const { t } = useTranslation();
  const query = useIntelligenceQuery<CompanyDiagnostics>("/company/diagnostics");
  if (query.isLoading) return <Loading />;
  return (
    <section className="space-y-4">
      <ErrorMessage error={query.error} />
      {query.data && (
        <>
          <p className="text-muted-foreground text-sm">
            {t("intel.publishedRevision")}: {query.data.published_revision} ·{" "}
            {query.data.as_of.slice(0, 10)}
          </p>
          {!query.data.published_revision && <p>{t("intel.noPublished")}</p>}
          <div className="grid grid-cols-3 gap-4 border-y py-4">
            {[
              [t("intel.reviews"), query.data.review_count],
              [t("intel.mapped"), query.data.mapped_review_count],
              [t("intel.unmapped"), query.data.unmapped_review_count],
            ].map(([label, value]) => (
              <div key={label}>
                <p className="text-muted-foreground text-xs">{label}</p>
                <p className="text-2xl font-semibold">{value}</p>
              </div>
            ))}
          </div>
          <p className="text-sm">
            {t("intel.dataStatus")}:{" "}
            {query.data.data_status === "available"
              ? t("intel.sufficient")
              : t("intel.insufficient")}
          </p>
          {!query.data.findings.length && <p>{t("intel.noFindings")}</p>}
          {query.data.findings.map((finding, i) => (
            <article
              key={`${finding.code}-${i}`}
              className={`space-y-2 border-l-2 p-3 ${finding.kind === "investigation_signal" ? "border-amber-600" : "border-muted-foreground"}`}
            >
              <h3 className="text-sm font-medium">{finding.subject === "company" ? t("intel.company") : finding.subject}</h3>
              <p className="text-sm" dir="auto">
                {finding.evidence}
              </p>
              <p className="text-muted-foreground text-sm" dir="auto">
                {finding.recommendation}
              </p>
            </article>
          ))}
          {query.data.process_metrics.map((metric) => (
            <p key={metric.process_id} className="border-b py-2 text-sm">
              {metric.process_id}: {metric.above_target}/{metric.samples} &gt;{" "}
              {metric.target_minutes} min ·{" "}
              {metric.status === "insufficient" ? t("intel.insufficient") : t("intel.sufficient")}
            </p>
          ))}
        </>
      )}
    </section>
  );
}
