"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTranslation } from "@/lib/i18n/use-translation";
import { CANCELLATION_REASON_LABELS } from "@/lib/ticket-actions";
import type { CancellationReason } from "@/lib/types";

interface CancelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (reason: CancellationReason) => void;
  isPending: boolean;
}

const REASON_OPTIONS: ReadonlyArray<CancellationReason> = [
  "false_positive",
  "duplicate",
  "spam",
  "off_topic",
  "other",
];

export function CancelDialog({ open, onOpenChange, onConfirm, isPending }: CancelDialogProps) {
  const { t } = useTranslation();
  const [reason, setReason] = useState<CancellationReason | "">("");

  function handleConfirm() {
    if (reason === "") return;
    onConfirm(reason);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("tickets.cancel.title")}</DialogTitle>
          <DialogDescription>{t("tickets.cancel.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="cancel-reason">{t("tickets.cancel.reasonLabel")}</Label>
          <Select value={reason} onValueChange={(v) => setReason(v as CancellationReason)}>
            <SelectTrigger id="cancel-reason">
              <SelectValue placeholder={t("tickets.cancel.reasonPlaceholder")} />
            </SelectTrigger>
            <SelectContent>
              {REASON_OPTIONS.map((r) => (
                <SelectItem key={r} value={r}>
                  {CANCELLATION_REASON_LABELS[r]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            {t("tickets.common.dismiss")}
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={reason === "" || isPending}
          >
            {isPending ? t("tickets.cancel.submitting") : t("tickets.cancel.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
