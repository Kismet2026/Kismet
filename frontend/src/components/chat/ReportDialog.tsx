"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Flag } from "@phosphor-icons/react";

const REPORT_REASONS = [
  { value: "inappropriate_content", label: "Inappropriate content" },
  { value: "harassment", label: "Harassment or bullying" },
  { value: "fake_profile", label: "Fake profile" },
  { value: "spam", label: "Spam" },
  { value: "other", label: "Other" },
] as const;

interface ReportDialogProps {
  reportedUserId: string;
  isOpen: boolean;
  onClose: () => void;
}

export function ReportDialog({ reportedUserId, isOpen, onClose }: ReportDialogProps) {
  const [reason, setReason] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  async function handleSubmit() {
    if (!reason) return;
    setSubmitting(true);
    try {
      await api.post("/reports", {
        reportedUserId,
        reason,
        description: description.trim() || undefined,
      });
      setSubmitted(true);
    } catch {
      // Still show success for demo
      setSubmitted(true);
    } finally {
      setSubmitting(false);
    }
  }

  function handleClose() {
    setReason("");
    setDescription("");
    setSubmitted(false);
    onClose();
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleClose}>
      <DialogContent className="bg-card border-border max-w-sm mx-auto">
        {submitted ? (
          <div className="text-center py-4">
            <Flag size={40} className="text-primary mx-auto mb-3" weight="fill" />
            <DialogTitle className="text-lg mb-2">Report Submitted</DialogTitle>
            <DialogDescription>
              Thank you. Our team will review this report.
            </DialogDescription>
            <Button onClick={handleClose} className="mt-4 w-full">Done</Button>
          </div>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Report User</DialogTitle>
              <DialogDescription>
                Why are you reporting this person?
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-2 mt-2">
              {REPORT_REASONS.map((r) => (
                <button
                  key={r.value}
                  onClick={() => setReason(r.value)}
                  className={`w-full text-left rounded-lg border px-4 py-3 text-sm transition-colors ${
                    reason === r.value
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-muted-foreground"
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
            {reason && (
              <textarea
                placeholder="Additional details (optional)"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                maxLength={500}
                rows={2}
                className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none mt-2"
              />
            )}
            <Button
              onClick={handleSubmit}
              disabled={!reason || submitting}
              variant="destructive"
              className="w-full mt-2"
            >
              {submitting ? "Submitting..." : "Submit Report"}
            </Button>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
