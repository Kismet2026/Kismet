"use client";

import { useState, useEffect, useCallback } from "react";
import { api, uploadToS3 } from "@/lib/api";
import { getUserIdFromToken } from "@/lib/auth";
import { normalizeImageFile } from "@/lib/imageUtils";
import type { Photo, PhotoUploadResponse } from "@/types";

export function usePhotos(userId?: string) {
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);

  const targetId = userId ?? getUserIdFromToken();

  const fetchPhotos = useCallback(async () => {
    if (!targetId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const data = await api.get<{ photos: Photo[]; count: number }>(
        `/users/${targetId}/photos`
      );
      setPhotos(data.photos);
    } catch {
      setPhotos([]);
    } finally {
      setLoading(false);
    }
  }, [targetId]);

  useEffect(() => {
    fetchPhotos();
  }, [fetchPhotos]);

  const uploadPhoto = useCallback(
    async (file: File): Promise<{ photoId: string; rejected: boolean }> => {
      setUploading(true);
      try {
        // Rekognition only accepts JPEG/PNG — convert WebP/HEIC/etc. so
        // D4 image-moderation can actually scan the upload.
        const normalized = await normalizeImageFile(file);
        const { uploadUrl, photoId } = await api.post<PhotoUploadResponse>(
          "/photos/upload",
          { contentType: normalized.type, filename: normalized.name }
        );
        await uploadToS3(uploadUrl, normalized);
        await api.post(`/photos/${photoId}/confirm`);

        // D4 moderation is async. Rekognition itself runs in 1-3s, but S3
        // eventual-consistency can force an in-Lambda retry (~3s extra), and
        // cold starts add ~500ms. Poll for up to ~15s, checking every 2s.
        // The backend hides rejected photos from GET /photos, so "missing
        // after settle" == flagged. We seed rejected=true and only flip it
        // once we've seen the photo appear *and* the terminal delay has
        // elapsed.
        let rejected = true;
        const pollIntervalMs = 2000;
        const maxAttempts = 8; // 8 × 2s ≈ 16s total
        for (let attempt = 0; attempt < maxAttempts; attempt++) {
          await new Promise((r) => setTimeout(r, pollIntervalMs));
          if (!targetId) break;
          try {
            const data = await api.get<{ photos: Photo[]; count: number }>(
              `/users/${targetId}/photos`
            );
            setPhotos(data.photos);
            const visible = data.photos.some((p) => p.photoId === photoId);
            if (visible) {
              // On the last attempt, photo is still there → approved.
              // Earlier attempts could still be mid-moderation (status=active
              // but not yet reviewed), so we keep polling to be sure.
              if (attempt >= maxAttempts - 1) {
                rejected = false;
                break;
              }
              // heuristic: if photo has survived ~6s it's very likely approved
              if (attempt >= 3) {
                rejected = false;
                break;
              }
            }
          } catch {
            // keep polling; single network blip shouldn't trigger the modal
          }
        }

        return { photoId, rejected };
      } finally {
        setUploading(false);
      }
    },
    [targetId]
  );

  const deletePhoto = useCallback(
    async (photoId: string) => {
      await api.delete(`/photos/${photoId}`);
      setPhotos((prev) => prev.filter((p) => p.photoId !== photoId));
    },
    []
  );

  const setPrimary = useCallback(
    async (photoId: string) => {
      await api.put(`/photos/${photoId}/primary`);
      setPhotos((prev) =>
        prev.map((p) => ({ ...p, isPrimary: p.photoId === photoId }))
      );
    },
    []
  );

  return { photos, loading, uploading, fetchPhotos, uploadPhoto, deletePhoto, setPrimary };
}
