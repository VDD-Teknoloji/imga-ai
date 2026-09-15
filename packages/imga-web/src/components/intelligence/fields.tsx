"use client";

import { useId, type ReactNode } from "react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useTranslation } from "@/lib/i18n/use-translation";

export function Field({
  label,
  value,
  onChange,
  multiline,
  type = "text",
  required,
  maxLength = 3000,
  disabled = false,
}: {
  label: string;
  value: string | number | null;
  onChange: (value: string) => void;
  multiline?: boolean;
  type?: string;
  required?: boolean;
  maxLength?: number;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="min-w-0 space-y-1.5">
      <label className="text-sm font-medium" htmlFor={id}>
        {label}
        {required ? <span aria-hidden="true"> *</span> : ""}
      </label>
      {multiline ? (
        <Textarea
          id={id}
          dir="auto"
          value={value ?? ""}
          onChange={(event) => onChange(event.target.value)}
          rows={4}
          maxLength={maxLength}
          disabled={disabled}
          required={required}
        />
      ) : (
        <Input
          id={id}
          dir={type === "text" ? "auto" : undefined}
          type={type}
          min={type === "number" ? 0 : undefined}
          value={value ?? ""}
          onChange={(event) => onChange(event.target.value)}
          maxLength={maxLength}
          disabled={disabled}
          required={required}
        />
      )}
    </div>
  );
}
export function Choice({
  label,
  value,
  onChange,
  options,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="min-w-0 space-y-1.5">
      <label className="text-sm font-medium" htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        className="border-input bg-background h-9 w-full min-w-0 rounded-md border px-2 text-sm disabled:opacity-60"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
export function ErrorMessage({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p
      role="alert"
      className="border-destructive text-destructive border-l-2 py-2 pl-3 text-sm break-words"
    >
      {error instanceof Error ? error.message : String(error)}
    </p>
  );
}
export function Workspace({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <main className="mx-auto w-full max-w-7xl space-y-6 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b pb-4">
        <h1 className="text-2xl font-semibold">{title}</h1>
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      </header>
      {children}
    </main>
  );
}
export function Loading() {
  const { t } = useTranslation();
  return (
    <p className="text-muted-foreground p-6 text-sm" role="status">
      {t("intel.loading")}
    </p>
  );
}
