"use client";

import { useState, useEffect, useCallback } from "react";
import { api, uploadToS3 } from "@/lib/api";
import { getUserIdFromToken } from "@/lib/auth";
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
    async (file: File) => {
      setUploading(true);
      try {
        // 1. Get presigned URL
        const { uploadUrl, photoId } = await api.post<PhotoUploadResponse>(
          "/photos/upload",
          { contentType: file.type, filename: file.name }
        );
        // 2. Upload directly to S3
        await uploadToS3(uploadUrl, file);
        // 3. Refresh photos list
        await fetchPhotos();
        return photoId;
      } finally {
        setUploading(false);
      }
    },
    [fetchPhotos]
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
