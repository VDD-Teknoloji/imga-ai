"use client";

// Veri Asistanı (2026-10-15) — yorum verisine soru-cevap.
//
// Sohbet geçmişi sayfa state'inde (sunucu durumsuz); son sorulan soru
// URL'de ``?q=`` olarak durur (url-state-patterns.md): F5/paylaşılan
// bağlantı aynı soruyu yeniden sorar. Her yanıtın kanıt paketi (dönem
// rakamları, artan konular, aşamalar, maskeli alıntılar) katlanır kart
// olarak gösterilir; alıntılar /reviews/[id]'ye bağlanır.

import { Bot, ChevronDown, ChevronUp, ExternalLink, Loader2, Send, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";

import { JourneyStageBadge } from "@/components/journey-stage-badge";
import { Loading, Workspace } from "@/components/intelligence/fields";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  useAskAssistant,
  useAssistantSuggestions,
  type AssistantAnswer,
  type AssistantTurn,
} from "@/hooks/use-assistant";
import { useTranslation } from "@/lib/i18n/use-translation";
import { journeyLabelKey } from "@/lib/journey";

interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  answer?: AssistantAnswer;
  error?: boolean;
}

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <AssistantPage />
    </Suspense>
  );
}

function AssistantPage() {
  const { t, locale } = useTranslation();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const ask = useAskAssistant();
  const suggestions = useAssistantSuggestions();
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  // Kendi meşgul bayrağı: useMutation.isPending StrictMode'un simüle
  // unmount'unda gözlemciyi kaybedip takılı kalabiliyor.
  const [busy, setBusy] = useState(false);
  const autoAsked = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const nf = new Intl.NumberFormat(locale === "en" ? "en-US" : "tr-TR");

  async function submit(question: string) {
    const trimmed = question.trim();
    if (!trimmed || busy) return;
    const history: AssistantTurn[] = messages
      .filter((m) => !m.error)
      .map((m) => ({ role: m.role, content: m.content }));
    const userId = Date.now();
    setMessages((prev) => [...prev, { id: userId, role: "user", content: trimmed }]);
    setDraft("");
    const next = new URLSearchParams(params.toString());
    next.set("q", trimmed);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    // mutateAsync: per-mutate callback'leri bileşen (StrictMode'da
    // simüle) unmount olunca düşer; promise her koşulda çözülür.
    setBusy(true);
    try {
      const data = await ask.mutateAsync({ question: trimmed, history });
      setMessages((prev) => [
        ...prev,
        { id: userId + 1, role: "assistant", content: data.answer, answer: data },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { id: userId + 1, role: "assistant", content: t("assistant.error"), error: true },
      ]);
    } finally {
      setBusy(false);
    }
  }

  const initialQuestion = params.get("q") ?? "";
  useEffect(() => {
    // Derin bağlantı: ?q= varsa bir kez otomatik sor (F5'te de aynı).
    if (autoAsked.current || !initialQuestion) return;
    autoAsked.current = true;
    submit(initialQuestion);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    submit(draft);
  }

  function clear() {
    setMessages([]);
    setDraft("");
    router.replace(pathname, { scroll: false });
  }

  const chips = suggestions.data?.items ?? [];

  return (
    <Workspace
      title={t("assistant.title")}
      actions={
        messages.length > 0 ? (
          <Button variant="outline" onClick={clear} disabled={busy}>
            <Trash2 />
            {t("assistant.clear")}
          </Button>
        ) : null
      }
    >
      <p className="text-muted-foreground max-w-prose text-sm">{t("assistant.subtitle")}</p>
      <p className="text-muted-foreground max-w-prose text-xs">{t("assistant.privacy")}</p>

      {chips.length > 0 ? (
        <section aria-label={t("assistant.suggestions")} className="space-y-2">
          <h2 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
            {t("assistant.suggestions")}
          </h2>
          <div className="flex flex-wrap gap-2">
            {chips.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => submit(item)}
                disabled={busy}
                className="bg-muted/60 hover:bg-muted rounded-full px-3 py-1.5 text-left text-sm disabled:opacity-60"
              >
                {item}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <section aria-live="polite" className="space-y-4">
        {messages.length === 0 && !busy ? (
          <p className="text-muted-foreground py-8 text-center text-sm">{t("assistant.empty")}</p>
        ) : null}
        {messages.map((message) =>
          message.role === "user" ? (
            <div key={message.id} className="flex justify-end">
              <div className="bg-primary text-primary-foreground max-w-[80%] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm">
                <span className="sr-only">{t("assistant.you")}: </span>
                {message.content}
              </div>
            </div>
          ) : (
            <AssistantMessage
              key={message.id}
              message={message}
              nf={nf}
              onFollowUp={submit}
              busy={busy}
            />
          ),
        )}
        {busy ? (
          <div className="text-muted-foreground flex items-center gap-2 text-sm">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            {t("assistant.asking")}
          </div>
        ) : null}
        <div ref={bottomRef} />
      </section>

      <form
        onSubmit={handleSubmit}
        className="bg-background sticky bottom-0 space-y-2 border-t pt-3"
      >
        <label htmlFor="assistant-question" className="sr-only">
          {t("assistant.ask")}
        </label>
        <div className="flex items-end gap-2">
          <Textarea
            id="assistant-question"
            dir="auto"
            rows={2}
            maxLength={500}
            value={draft}
            placeholder={t("assistant.placeholder")}
            disabled={busy}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit(draft);
              }
            }}
          />
          <Button type="submit" disabled={busy || !draft.trim()}>
            <Send />
            {t("assistant.ask")}
          </Button>
        </div>
      </form>
    </Workspace>
  );
}

function AssistantMessage({
  message,
  nf,
  onFollowUp,
  busy,
}: {
  message: Message;
  nf: Intl.NumberFormat;
  onFollowUp: (question: string) => void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const answer = message.answer;
  return (
    <div className="flex gap-3">
      <div className="bg-muted mt-1 flex size-8 shrink-0 items-center justify-center rounded-full">
        <Bot className="size-4" aria-hidden />
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        <div
          className={`bg-card max-w-[90%] rounded-2xl rounded-tl-sm border px-4 py-3 text-sm whitespace-pre-line ${
            message.error ? "border-destructive text-destructive" : ""
          }`}
          dir="auto"
        >
          <span className="sr-only">{t("assistant.bot")}: </span>
          {message.content}
        </div>
        {answer ? (
          <>
            {answer.highlights.length > 0 ? (
              <ul className="ml-1 list-disc space-y-1 pl-4 text-sm">
                {answer.highlights.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}
            {!answer.llm_used ? (
              <p className="text-muted-foreground text-xs">{t("assistant.ruleBased")}</p>
            ) : answer.model ? (
              <p className="text-muted-foreground text-xs">
                {t("assistant.model")}: {answer.model}
              </p>
            ) : null}
            {answer.data_gaps.length > 0 ? (
              <p className="text-muted-foreground text-xs">
                {t("assistant.dataGaps")}: {answer.data_gaps.join(" · ")}
              </p>
            ) : null}
            {answer.follow_ups.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {answer.follow_ups.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => onFollowUp(item)}
                    disabled={busy}
                    className="hover:bg-muted rounded-full border px-3 py-1 text-left text-xs disabled:opacity-60"
                  >
                    {item}
                  </button>
                ))}
              </div>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-auto px-2 py-1 text-xs"
              aria-expanded={open}
              onClick={() => setOpen((value) => !value)}
            >
              {open ? <ChevronUp /> : <ChevronDown />}
              {open ? t("assistant.evidenceHide") : t("assistant.evidence")}
            </Button>
            {open ? <EvidenceCard answer={answer} nf={nf} /> : null}
          </>
        ) : null}
      </div>
    </div>
  );
}

function pctText(value: number | null): string {
  if (value === null) return "—";
  return `${value > 0 ? "+" : ""}${value}%`;
}

function EvidenceCard({ answer, nf }: { answer: AssistantAnswer; nf: Intl.NumberFormat }) {
  const { t } = useTranslation();
  const { scope, evidence } = answer;
  const cur = evidence.current;
  const prev = evidence.previous;
  const listParams = new URLSearchParams({
    date_from: scope.current.from,
    date_to: scope.current.to,
  });
  if (scope.focus_category) listParams.set("primary_categories", scope.focus_category);
  if (scope.focus_stage) listParams.set("journey_stages", scope.focus_stage);
  const focusLabel = scope.focus_category_label ?? scope.focus_stage_label;
  const stageRows = Object.entries(evidence.stage_delta).filter(
    ([, v]) => v.current > 0 || v.previous > 0,
  );
  return (
    <div className="bg-card space-y-4 rounded-xl border p-4 text-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span>
          <span className="text-muted-foreground">{t("assistant.period")}:</span>{" "}
          <strong>{scope.period_label}</strong> ({scope.current.from} – {scope.current.to})
        </span>
        <span className="text-muted-foreground">
          {t("assistant.previousPeriod")}: {scope.previous.from} – {scope.previous.to}
        </span>
        <span>
          <span className="text-muted-foreground">{t("assistant.focus")}:</span>{" "}
          {focusLabel ?? t("assistant.noFocus")}
        </span>
        <Link
          href={`/reviews?${listParams.toString()}`}
          className="text-primary inline-flex items-center gap-1 underline-offset-4 hover:underline"
        >
          {t("assistant.openList")}
          <ExternalLink className="size-3.5" aria-hidden />
        </Link>
      </div>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          label={t("assistant.allReviews")}
          value={nf.format(cur.total)}
          note={`${t("assistant.vsPrevious", { count: nf.format(prev.total) })} · ${pctText(evidence.overall_delta.total_pct_change)}`}
        />
        <Stat
          label={t("assistant.negativeShare")}
          value={`%${cur.negative_share}`}
          note={`${t("assistant.vsPrevious", { count: `%${prev.negative_share}` })}`}
        />
        {cur.focus && prev.focus && evidence.focus_delta ? (
          <>
            <Stat
              label={t("assistant.focusTotal")}
              value={nf.format(cur.focus.total)}
              note={`${t("assistant.vsPrevious", { count: nf.format(prev.focus.total) })} · ${pctText(evidence.focus_delta.total_pct_change)}`}
            />
            <Stat
              label={t("assistant.focusNegative")}
              value={nf.format(cur.focus.negatif)}
              note={`${t("assistant.vsPrevious", { count: nf.format(prev.focus.negatif) })} · ${pctText(evidence.focus_delta.negatif_pct_change)}`}
            />
          </>
        ) : null}
      </dl>
      {evidence.focus_delta?.sample_status === "insufficient" ? (
        <p className="text-muted-foreground text-xs">{t("assistant.insufficient")}</p>
      ) : null}

      {cur.focus && cur.focus.perspectives.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {cur.focus.perspectives.slice(0, 6).map((p) => (
            <span key={p.code} className="bg-muted rounded-full px-2 py-0.5 text-xs">
              {p.label ?? p.code} · {nf.format(p.total)}
            </span>
          ))}
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <MoverTable
          title={t("assistant.movers")}
          rows={evidence.category_movers.filter((m) => m.diff > 0)}
          nf={nf}
        />
        <MoverTable
          title={t("assistant.fallers")}
          rows={evidence.category_fallers.filter((m) => m.diff < 0)}
          nf={nf}
        />
      </div>

      {stageRows.length > 0 ? (
        <div>
          <h3 className="mb-1 font-medium">{t("assistant.stages")}</h3>
          <ul className="flex flex-wrap gap-2 text-xs">
            {stageRows.map(([stage, v]) => (
              <li
                key={stage}
                className="bg-muted flex items-center gap-1.5 rounded-full px-2 py-0.5"
              >
                <JourneyStageBadge stage={stage === "atanmamis" ? null : stage} showUnassigned />
                <span className="tabular-nums">
                  {nf.format(v.current)}
                  <span className="text-muted-foreground"> / {nf.format(v.previous)}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {evidence.quotes.length > 0 ? (
        <div>
          <h3 className="mb-1 font-medium">{t("assistant.quotes")}</h3>
          <ol className="space-y-2">
            {evidence.quotes.map((q) => (
              <li key={q.review_id} className="border-l-2 pl-3">
                <p dir="auto">
                  <span className="text-muted-foreground mr-1 text-xs">[#{q.ref}]</span>
                  {q.text}
                </p>
                <p className="text-muted-foreground mt-0.5 flex flex-wrap items-center gap-x-2 text-xs">
                  <span>{q.date}</span>
                  {q.source ? <span>{q.source}</span> : null}
                  <span>{q.category}</span>
                  {q.perspective_label ? <span>{q.perspective_label}</span> : null}
                  {q.stage ? <span>{t(journeyLabelKey(q.stage))}</span> : null}
                  <Link
                    href={`/reviews/${q.review_id}`}
                    className="text-primary underline-offset-4 hover:underline"
                  >
                    {t("assistant.openReview")}
                  </Link>
                </p>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums">{value}</dd>
      <dd className="text-muted-foreground text-xs">{note}</dd>
    </div>
  );
}

function MoverTable({
  title,
  rows,
  nf,
}: {
  title: string;
  rows: AssistantAnswer["evidence"]["category_movers"];
  nf: Intl.NumberFormat;
}) {
  if (rows.length === 0) return null;
  return (
    <div>
      <h3 className="mb-1 font-medium">{title}</h3>
      <table className="w-full text-xs">
        <tbody>
          {rows.slice(0, 5).map((m) => (
            <tr key={m.code} className="border-b last:border-b-0">
              <td className="py-1 pr-2">{m.label}</td>
              <td className="py-1 text-right tabular-nums">
                {nf.format(m.previous)} → <strong>{nf.format(m.current)}</strong>
              </td>
              <td
                className={`py-1 pl-2 text-right tabular-nums ${
                  m.diff > 0 ? "text-sentiment-negative" : "text-emerald-700 dark:text-emerald-400"
                }`}
              >
                {m.diff > 0 ? "+" : ""}
                {nf.format(m.diff)} ({pctText(m.pct_change)})
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
