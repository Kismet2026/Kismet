"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, MapPin, CaretLeft, CaretRight } from "@phosphor-icons/react";
import { BaziScoreBadge } from "./BaziScoreBadge";
import { api } from "@/lib/api";
import type { Candidate, Photo, UserProfile } from "@/types";

interface ProfileDetailProps {
  candidate: Candidate | null;
  isOpen: boolean;
  onClose: () => void;
}

export function ProfileDetail({ candidate, isOpen, onClose }: ProfileDetailProps) {
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [interests, setInterests] = useState<string[]>([]);
  const [photoIndex, setPhotoIndex] = useState(0);

  // Fetch full profile + photos when opened
  useEffect(() => {
    if (!isOpen || !candidate) return;
    setPhotoIndex(0);

    // Fetch photos
    api.get<{ photos: Photo[] }>(`/users/${candidate.userId}/photos`)
      .then((data) => {
        const sorted = (data.photos || []).sort((a, b) =>
          a.isPrimary === b.isPrimary ? 0 : a.isPrimary ? -1 : 1
        );
        setPhotos(sorted);
      })
      .catch(() => setPhotos([]));

    // Fetch full profile for interests (candidate may not have them)
    if (candidate.interests && candidate.interests.length > 0) {
      setInterests(candidate.interests);
    } else {
      api.get<UserProfile>(`/profiles/${candidate.userId}`)
        .then((p) => setInterests(p.interests || []))
        .catch(() => setInterests([]));
    }
  }, [isOpen, candidate]);

  if (!candidate) return null;

  const placeholderBg = `hsl(${candidate.userId.charCodeAt(0) * 7 % 360}, 25%, 20%)`;
  const displayPhotos = photos.length > 0
    ? photos
    : candidate.avatarUrl
      ? [{ photoId: "primary", url: candidate.avatarUrl, isPrimary: true, uploadedAt: "" }]
      : [];
  const currentPhoto = displayPhotos[photoIndex];

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed inset-0 z-50 flex flex-col"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" onClick={onClose} />

          <motion.div
            className="relative z-10 flex-1 overflow-y-auto"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
          >
            {/* Photo gallery header */}
            <div className="relative h-[55dvh] bg-card">
              {currentPhoto ? (
                <img
                  src={currentPhoto.url}
                  alt={candidate.displayName}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div
                  className="w-full h-full flex items-center justify-center text-8xl font-bold text-foreground/20"
                  style={{ background: placeholderBg }}
                >
                  {candidate.displayName.charAt(0).toUpperCase()}
                </div>
              )}
              <div className="absolute inset-0 bg-gradient-to-t from-background via-transparent to-transparent pointer-events-none" />

              {/* Photo navigation */}
              {displayPhotos.length > 1 && (
                <>
                  {/* Dots indicator at top */}
                  <div className="absolute top-4 left-0 right-0 flex justify-center gap-1.5 px-16">
                    {displayPhotos.map((_, i) => (
                      <div
                        key={i}
                        className={`h-1 flex-1 rounded-full transition-colors ${
                          i === photoIndex ? "bg-white" : "bg-white/30"
                        }`}
                      />
                    ))}
                  </div>

                  {/* Prev/next buttons */}
                  {photoIndex > 0 && (
                    <button
                      onClick={() => setPhotoIndex((i) => i - 1)}
                      className="absolute left-2 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-black/40 flex items-center justify-center text-white"
                    >
                      <CaretLeft size={20} weight="bold" />
                    </button>
                  )}
                  {photoIndex < displayPhotos.length - 1 && (
                    <button
                      onClick={() => setPhotoIndex((i) => i + 1)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-black/40 flex items-center justify-center text-white"
                    >
                      <CaretRight size={20} weight="bold" />
                    </button>
                  )}
                </>
              )}

              {/* Close button */}
              <button
                onClick={onClose}
                className="absolute top-4 right-4 w-10 h-10 rounded-full bg-black/50 flex items-center justify-center text-white"
              >
                <X size={20} weight="bold" />
              </button>
            </div>

            {/* Info */}
            <div className="px-5 pb-8 -mt-8 relative">
              <h2 className="text-3xl font-bold text-foreground">
                {candidate.displayName}
                {candidate.age && (
                  <span className="font-normal text-muted-foreground">, {candidate.age}</span>
                )}
              </h2>

              {candidate.city && (
                <p className="text-sm text-muted-foreground flex items-center gap-1 mt-1">
                  <MapPin size={14} /> {candidate.city}
                </p>
              )}

              {(candidate.baziScore != null || candidate.reverseBaziScore != null) && (
                <div className="mt-4 bg-card rounded-xl p-4 space-y-3">
                  <p className="text-xs text-muted-foreground">BaZi Compatibility</p>
                  {candidate.baziScore != null && (
                    <div className="flex items-center gap-3">
                      <BaziScoreBadge score={candidate.baziScore} size="sm" />
                      <div className="flex-1">
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Your score for them</p>
                        <p className="text-sm text-foreground">
                          {candidate.baziScore >= 90
                            ? "Exceptional match — the stars truly align!"
                            : candidate.baziScore >= 70
                              ? "Strong compatibility"
                              : "Moderate compatibility"}
                        </p>
                      </div>
                    </div>
                  )}
                  {candidate.reverseBaziScore != null && (
                    <div className="flex items-center gap-3">
                      <BaziScoreBadge score={candidate.reverseBaziScore} size="sm" />
                      <div className="flex-1">
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Their score for you</p>
                        <p className="text-sm text-foreground">
                          {candidate.reverseBaziScore >= 90
                            ? "They find you exceptional!"
                            : candidate.reverseBaziScore >= 70
                              ? "They see strong compatibility"
                              : "They see moderate compatibility"}
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {candidate.bio && (
                <div className="mt-4 bg-card rounded-xl p-4">
                  <p className="text-xs text-muted-foreground mb-1">About</p>
                  <p className="text-sm text-foreground leading-relaxed">{candidate.bio}</p>
                </div>
              )}

              {interests.length > 0 && (
                <div className="mt-4 bg-card rounded-xl p-4">
                  <p className="text-xs text-muted-foreground mb-2">Interests</p>
                  <div className="flex flex-wrap gap-2">
                    {interests.map((interest) => (
                      <span
                        key={interest}
                        className="rounded-full bg-primary/10 text-primary px-3 py-1 text-xs"
                      >
                        {interest}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Photo thumbnails grid */}
              {displayPhotos.length > 1 && (
                <div className="mt-4 bg-card rounded-xl p-4">
                  <p className="text-xs text-muted-foreground mb-2">Photos</p>
                  <div className="grid grid-cols-3 gap-2">
                    {displayPhotos.map((photo, i) => (
                      <button
                        key={photo.photoId}
                        onClick={() => setPhotoIndex(i)}
                        className={`aspect-square rounded-lg overflow-hidden border-2 transition-colors ${
                          i === photoIndex ? "border-primary" : "border-transparent"
                        }`}
                      >
                        <img
                          src={photo.url}
                          alt={`Photo ${i + 1}`}
                          className="w-full h-full object-cover"
                        />
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
