"use client";

import { useRef } from "react";
import { Plus, X, Star } from "@phosphor-icons/react";
import type { Photo } from "@/types";
import { cn } from "@/lib/utils";

interface PhotoUploaderProps {
  photos: Photo[];
  uploading: boolean;
  onUpload: (file: File) => Promise<void>;
  onDelete: (photoId: string) => Promise<void>;
  onSetPrimary: (photoId: string) => Promise<void>;
  maxPhotos?: number;
}

export function PhotoUploader({
  photos,
  uploading,
  onUpload,
  onDelete,
  onSetPrimary,
  maxPhotos = 6,
}: PhotoUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    // Basic validation
    if (!file.type.startsWith("image/")) return;
    if (file.size > 10 * 1024 * 1024) return; // 10MB max
    onUpload(file);
    // Reset input so same file can be re-selected
    e.target.value = "";
  }

  // Build 2x3 grid: fill with photos + empty slots
  const slots = Array.from({ length: maxPhotos }, (_, i) => photos[i] ?? null);

  return (
    <div className="space-y-3">
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        onChange={handleFileChange}
        className="hidden"
      />
      <div className="grid grid-cols-3 gap-2">
        {slots.map((photo, i) => (
          <div
            key={photo?.photoId ?? `empty-${i}`}
            className={cn(
              "relative aspect-[3/4] rounded-xl overflow-hidden border-2 transition-colors",
              photo
                ? "border-transparent"
                : "border-dashed border-muted-foreground/30 hover:border-primary/50"
            )}
          >
            {photo ? (
              <>
                <img
                  src={photo.url}
                  alt={`Photo ${i + 1}`}
                  className="w-full h-full object-cover"
                />
                {/* Primary badge */}
                {photo.isPrimary && (
                  <div className="absolute top-1.5 left-1.5 rounded-full bg-primary p-1">
                    <Star size={12} weight="fill" className="text-primary-foreground" />
                  </div>
                )}
                {/* Actions overlay */}
                <div className="absolute top-1.5 right-1.5 flex gap-1">
                  {!photo.isPrimary && (
                    <button
                      onClick={() => onSetPrimary(photo.photoId)}
                      className="rounded-full bg-black/60 p-1.5 text-white hover:bg-black/80 transition-colors"
                      title="Set as primary"
                    >
                      <Star size={14} />
                    </button>
                  )}
                  <button
                    onClick={() => onDelete(photo.photoId)}
                    className="rounded-full bg-black/60 p-1.5 text-white hover:bg-destructive transition-colors"
                    title="Delete"
                  >
                    <X size={14} />
                  </button>
                </div>
              </>
            ) : (
              <button
                onClick={() => inputRef.current?.click()}
                disabled={uploading}
                className="w-full h-full flex flex-col items-center justify-center gap-1 text-muted-foreground hover:text-primary transition-colors"
              >
                <Plus size={24} weight={uploading && i === photos.length ? "bold" : "light"} />
                {uploading && i === photos.length ? (
                  <span className="text-[10px]">Uploading...</span>
                ) : (
                  <span className="text-[10px]">Add</span>
                )}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
