"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ShieldWarning } from "@phosphor-icons/react";

interface PhotoRejectedDialogProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Shown when an uploaded photo is rejected by the D4 moderation pipeline
 * (AWS Rekognition flagged nudity, violence, weapons, etc). We can't surface
 * the exact reason to users without inviting gaming, so we keep it generic.
 */
export function PhotoRejectedDialog({ open, onClose }: PhotoRejectedDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
            <ShieldWarning size={24} className="text-destructive" weight="fill" />
          </div>
          <DialogTitle className="text-center">Photo couldn&apos;t be uploaded</DialogTitle>
          <DialogDescription className="text-center">
            Our content review flagged this image as inappropriate. Please pick a different photo —
            a clear selfie works best.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button onClick={onClose} className="w-full">
            Got it
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
