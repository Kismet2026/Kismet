"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { usePhotos } from "@/hooks/usePhotos";
import { PhotoUploader } from "@/components/profile/PhotoUploader";
import { PhotoRejectedDialog } from "@/components/profile/PhotoRejectedDialog";
import { Button } from "@/components/ui/button";
import { Camera } from "@phosphor-icons/react";

export default function OnboardingPhotosPage() {
  const router = useRouter();
  const { photos, uploading, uploadPhoto, deletePhoto, setPrimary } = usePhotos();
  const [rejectedOpen, setRejectedOpen] = useState(false);

  const canContinue = photos.length >= 1;

  return (
    <div className="flex-1 px-4 py-6 max-w-md mx-auto w-full flex flex-col">
      <div className="text-center mb-6">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
          <Camera size={24} className="text-primary" weight="fill" />
        </div>
        <h1 className="text-2xl font-bold">Add Photos</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Add at least 1 photo to continue. Your first photo will be your avatar.
        </p>
      </div>

      <div className="flex-1">
        <PhotoUploader
          photos={photos}
          uploading={uploading}
          onUpload={async (file) => {
            const { rejected } = await uploadPhoto(file);
            if (rejected) setRejectedOpen(true);
          }}
          onDelete={async (id) => { await deletePhoto(id); }}
          onSetPrimary={async (id) => { await setPrimary(id); }}
        />
      </div>

      <PhotoRejectedDialog open={rejectedOpen} onClose={() => setRejectedOpen(false)} />

      <div className="mt-6 space-y-3">
        <Button
          onClick={() => router.push("/discover")}
          className="w-full"
          disabled={!canContinue}
        >
          {canContinue ? "Start Discovering" : "Add at least 1 photo"}
        </Button>
        <button
          onClick={() => router.push("/discover")}
          className="w-full text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          Skip for now
        </button>
      </div>
    </div>
  );
}
