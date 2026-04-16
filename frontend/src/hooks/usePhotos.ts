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

        // D4 moderation is async (Rekognition typically ~1-3s). Wait long
        // enough for the scan to settle, then check whether the photo is
        // still in the list — the backend filters out rejected photos so
        // missing == flagged.
        await new Promise((r) => setTimeout(r, 5000));
        let rejected = true;
        if (targetId) {
          try {
            const data = await api.get<{ photos: Photo[]; count: number }>(
              `/users/${targetId}/photos`
            );
            setPhotos(data.photos);
            rejected = !data.photos.some((p) => p.photoId === photoId);
          } catch {
            // network failure — assume not rejected rather than lie to user
            rejected = false;
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
