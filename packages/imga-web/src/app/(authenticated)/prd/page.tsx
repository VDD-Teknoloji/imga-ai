"use client";

import { Suspense, useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Check, Download, History, Plus, Save, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DocumentHistory } from "@/components/intelligence/document-history";
import { Choice, ErrorMessage, Field, Loading, Workspace } from "@/components/intelligence/fields";
import {
  downloadIntelligence,
  useIntelligenceQuery,
  useIntelligenceTenant,
  useIntelligenceUrl,
  useSaveDocument,
} from "@/hooks/use-intelligence";
import { useRoleFlags } from "@/hooks/use-role-flags";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { DocumentSnapshot, PrdDocument, PrdSection } from "@/lib/intelligence-types";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <PrdLoader />
    </Suspense>
  );
}
function PrdLoader() {
  const tenant = useIntelligenceTenant();
  const query = useIntelligenceQuery<DocumentSnapshot<PrdDocument>>("/documents/prd");
  if (query.isLoading) return <Loading />;
  if (!query.data) return <ErrorMessage error={query.error} />;
  return <PrdEditor key={tenant} initial={query.data} />;
}
function PrdEditor({ initial }: { initial: DocumentSnapshot<PrdDocument> }) {
  const { t } = useTranslation();
  const { canWrite, isAdmin } = useRoleFlags();
  const { params, change } = useIntelligenceUrl();
  const [snapshot, setSnapshot] = useState(initial);
  const [draft, setDraft] = useState(initial.content);
  const [error, setError] = useState<unknown>(null);
  const save = useSaveDocument<PrdDocument>("prd");
  const latest = useIntelligenceQuery<DocumentSnapshot<PrdDocument>>("/documents/prd");
  const dirty = JSON.stringify(draft) !== JSON.stringify(snapshot.content);
  // The API contract requires at least one section; deletion preserves that invariant.
  const selected = (draft.sections.find((section) => section.id === params.get("section")) ??
    draft.sections[0])!;
  const index = draft.sections.findIndex((section) => section.id === selected.id);
  const history = params.get("view") === "history";
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function patch(values: Partial<PrdSection>) {
    setDraft((previous) => ({
      ...previous,
      sections: previous.sections.map((section) =>
        section.id === selected.id ? {
          ...section,
          ...values,
          status: values.status ?? (section.status === "confirmed" ? "draft" : section.status),
        } : section,
      ),
    }));
  }
  async function persist(status: "draft" | "approved") {
    setError(null);
    try {
      const result = await save.mutateAsync({
        content: draft,
        expected_revision: snapshot.revision,
        status,
      });
      setSnapshot(result);
      setDraft(result.content);
    } catch (cause) {
      setError(cause);
    }
  }
  function move(delta: number) {
    const sections = [...draft.sections];
    const current = sections[index];
    const target = sections[index + delta];
    if (!current || !target) return;
    [sections[index], sections[index + delta]] = [target, current];
    setDraft({ ...draft, sections });
  }
  const states = ["open", "draft", "confirmed", "not_applicable"] as const;
  return (
    <Workspace
      title={t("intel.prd")}
      actions={
        <>
          <Button variant="outline" onClick={() => change({ view: history ? "" : "history" })}>
            <History />
            {t(history ? "intel.current" : "intel.history")}
          </Button>
          <Button
            variant="outline"
            title={t("intel.download")}
            aria-label={t("intel.download")}
            onClick={() => downloadIntelligence("/prd/export", "imga-prd.md").catch(setError)}
          >
            <Download />
          </Button>
          {canWrite && !history && (
            <Button disabled={save.isPending} onClick={() => persist("draft")}>
              <Save />
              {t("intel.save")}
            </Button>
          )}
          {isAdmin && !history && (
            <Button variant="outline" disabled={save.isPending} onClick={() => persist("approved")}>
              <Check />
              {t("intel.publish")}
            </Button>
          )}
        </>
      }
    >
      <ErrorMessage error={error} />
      <div className="text-muted-foreground flex flex-wrap items-center gap-4 text-sm">
        <span>
          {t("intel.revision")} {snapshot.revision} · {t(`intel.${snapshot.status}`)}
        </span>
        <span>{dirty ? t("intel.unsaved") : t("intel.saved")}</span>
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
        {!canWrite && <span>{t("intel.readOnly")}</span>}
      </div>
      {history ? (
        <DocumentHistory<PrdDocument>
          kind="prd"
          render={(document) => (
            <>
              <h2 className="font-semibold">{document.title}</h2>
              {document.sections.map((section) => (
                <section key={section.id} className="space-y-2 border-b pb-3">
                  <h3 className="font-medium">
                    {section.title} · {t(`intel.${section.status}`)}
                  </h3>
                  <p className="break-words whitespace-pre-wrap" dir="auto">
                    {section.answer}
                  </p>
                  <p className="break-words">
                    {t("intel.evidence")}: {section.evidence}
                  </p>
                  <p>
                    {t("intel.acceptance")}: {section.acceptance}
                  </p>
                  <p>
                    {t("intel.owner")}: {section.owner}
                  </p>
                </section>
              ))}
            </>
          )}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-5">
            <div className="min-w-52 flex-1">
              <Field
                label={t("intel.title")}
                value={draft.title}
                maxLength={160}
                disabled={!canWrite}
                onChange={(title) => setDraft({ ...draft, title })}
              />
            </div>
            <div className="w-56 space-y-1 text-sm">
              <p>
                {t("intel.maturity")}: {snapshot.interview?.confirmed ?? 0} /{" "}
                {snapshot.interview?.total ?? 16}
              </p>
              <progress
                className="h-2 w-full accent-emerald-600"
                value={snapshot.interview?.maturity_percent ?? 0}
                max={100}
                aria-label={t("intel.maturity")}
              />
            </div>
          </div>
          <div className="grid items-start gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
            <nav
              className="flex max-h-80 flex-col overflow-auto border-y lg:max-h-[65vh]"
              aria-label={t("intel.prd")}
            >
              {draft.sections.map((section, i) => (
                <button
                  key={section.id}
                  className={`flex min-h-12 items-start gap-2 border-b px-3 py-3 text-left text-sm ${selected.id === section.id ? "bg-accent font-semibold" : "hover:bg-muted"}`}
                  aria-current={selected.id === section.id ? "step" : undefined}
                  onClick={() => change({ section: section.id })}
                >
                  <span className="text-muted-foreground w-5 shrink-0">{i + 1}.</span>
                  <span className="min-w-0 break-words">{section.title}</span>
                  {section.status === "confirmed" && (
                    <Check className="ml-auto size-4 shrink-0 text-emerald-600" />
                  )}
                </button>
              ))}
              {canWrite && (
                <Button
                  variant="ghost"
                  disabled={draft.sections.length >= 64}
                  onClick={() => {
                    const id = `section_${crypto.randomUUID().slice(0, 8)}`;
                    setDraft({
                      ...draft,
                      sections: [
                        ...draft.sections,
                        {
                          id,
                          title: t("intel.newSection"),
                          question: t("intel.newQuestion"),
                          answer: "",
                          evidence: "",
                          acceptance: "",
                          owner: "",
                          status: "open",
                        },
                      ],
                    });
                    change({ section: id });
                  }}
                >
                  <Plus />
                  {t("intel.addSection")}
                </Button>
              )}
            </nav>
            <section className="min-w-0 space-y-4">
              <fieldset disabled={!canWrite || save.isPending} className="space-y-4">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <Field
                      label={t("intel.title")}
                      value={selected.title}
                      maxLength={160}
                      onChange={(title) => patch({ title })}
                    />
                  </div>
                  <div className="flex gap-1 pt-6">
                    {[
                      { icon: ArrowUp, delta: -1, key: "up", disabled: index === 0 },
                      {
                        icon: ArrowDown,
                        delta: 1,
                        key: "down",
                        disabled: index === draft.sections.length - 1,
                      },
                    ].map((item) => (
                      <Button
                        key={item.key}
                        size="icon"
                        variant="ghost"
                        title={t(`intel.${item.key}`)}
                        aria-label={t(`intel.${item.key}`)}
                        disabled={item.disabled}
                        onClick={() => move(item.delta)}
                      >
                        <item.icon />
                      </Button>
                    ))}
                    <Button
                      size="icon"
                      variant="ghost"
                      title={t("intel.remove")}
                      aria-label={t("intel.remove")}
                      disabled={draft.sections.length <= 1}
                      onClick={() => {
                        if (window.confirm(t("intel.remove") + ": " + selected.title + "?"))
                          setDraft({
                            ...draft,
                            sections: draft.sections.filter(
                              (section) => section.id !== selected.id,
                            ),
                          });
                      }}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </div>
                <Field
                  label={t("intel.question")}
                  value={selected.question}
                  maxLength={1000}
                  onChange={(question) => patch({ question })}
                />
                <Field
                  label={t("intel.answer")}
                  value={selected.answer}
                  maxLength={12000}
                  multiline
                  onChange={(answer) =>
                    patch({
                      answer,
                      status: selected.status === "confirmed" ? "draft" : selected.status,
                    })
                  }
                />
                <div className="grid gap-4 md:grid-cols-2">
                  <Field
                    label={t("intel.evidence")}
                    value={selected.evidence}
                    multiline
                    onChange={(evidence) => patch({ evidence })}
                  />
                  <Field
                    label={t("intel.acceptance")}
                    value={selected.acceptance}
                    multiline
                    onChange={(acceptance) => patch({ acceptance })}
                  />
                  <Field
                    label={t("intel.owner")}
                    value={selected.owner}
                    maxLength={160}
                    onChange={(owner) => patch({ owner })}
                  />
                  <Choice
                    label={t("intel.status")}
                    value={selected.status}
                    options={states.map((value) => ({ value, label: t(`intel.${value}`) }))}
                    onChange={(status) => patch({ status: status as PrdSection["status"] })}
                  />
                </div>
              </fieldset>
              {snapshot.interview?.questions.find(
                (question) => question.section_id === selected.id,
              ) && (
                <aside className="bg-muted/40 space-y-1 border-l-2 border-emerald-600 p-4 text-sm">
                  <h3 className="font-medium">{t("intel.savedQuestions")}</h3>
                  <p>
                    {
                      snapshot.interview.questions.find(
                        (question) => question.section_id === selected.id,
                      )?.question
                    }
                  </p>
                </aside>
              )}
            </section>
          </div>
        </>
      )}
    </Workspace>
  );
}
