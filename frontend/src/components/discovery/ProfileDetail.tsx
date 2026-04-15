"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence, type PanInfo } from "framer-motion";
import { X, MapPin, Heart } from "@phosphor-icons/react";
import { YinYangScore } from "./YinYangScore";
import { api } from "@/lib/api";
import type { Candidate, Photo, UserProfile } from "@/types";

interface ProfileDetailProps {
  candidate: Candidate | null;
  isOpen: boolean;
  onClose: () => void;
  onSwipe?: (action: "like" | "pass") => void;
}

export function ProfileDetail({ candidate, isOpen, onClose, onSwipe }: ProfileDetailProps) {
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [interests, setInterests] = useState<string[]>([]);
  const [photoIndex, setPhotoIndex] = useState(0);

  useEffect(() => {
    if (!isOpen || !candidate) return;
    setPhotoIndex(0);

    api.get<{ photos: Photo[] }>(`/users/${candidate.userId}/photos`)
      .then((data) => {
        const sorted = (data.photos || []).sort((a, b) =>
          a.isPrimary === b.isPrimary ? 0 : a.isPrimary ? -1 : 1
        );
        setPhotos(sorted);
      })
      .catch(() => setPhotos([]));

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
  const photoCount = displayPhotos.length;

  function handlePhotoDragEnd(_: unknown, info: PanInfo) {
    if (info.offset.x < -50 && photoIndex < photoCount - 1) {
      setPhotoIndex((i) => i + 1);
    } else if (info.offset.x > 50 && photoIndex > 0) {
      setPhotoIndex((i) => i - 1);
    }
  }

  function handleTapZone(side: "left" | "right") {
    if (side === "left" && photoIndex > 0) setPhotoIndex((i) => i - 1);
    if (side === "right" && photoIndex < photoCount - 1) setPhotoIndex((i) => i + 1);
  }

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed inset-0 z-50"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          {/* Brand-palette background — plum gradient + ambient glows */}
          <div className="absolute inset-0 bg-background">
            {/* Amber ambient glow top-right */}
            <div
              className="absolute top-0 right-0 w-[70%] h-[50%] opacity-30 pointer-events-none"
              style={{
                background:
                  "radial-gradient(ellipse at top right, rgba(212,160,86,0.35), transparent 60%)",
              }}
            />
            {/* Mauve ambient glow bottom-left */}
            <div
              className="absolute bottom-0 left-0 w-[80%] h-[60%] opacity-40 pointer-events-none"
              style={{
                background:
                  "radial-gradient(ellipse at bottom left, rgba(167,130,149,0.25), transparent 60%)",
              }}
            />
            {/* Base tint overlay */}
            <div className="absolute inset-0 bg-gradient-to-b from-[#2a1724] via-background to-[#1f1119]" />
          </div>

          <motion.div
            className="relative z-10 h-full flex flex-col overflow-y-auto"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", damping: 28, stiffness: 300 }}
          >
            {/* Photo hero — swipeable */}
            <div className="relative h-[62dvh] flex-shrink-0 overflow-hidden">
              <motion.div
                className="absolute inset-0 touch-pan-y"
                drag={photoCount > 1 ? "x" : false}
                dragConstraints={{ left: 0, right: 0 }}
                dragElastic={0.15}
                onDragEnd={handlePhotoDragEnd}
              >
                <AnimatePresence mode="wait" initial={false}>
                  <motion.div
                    key={photoIndex}
                    className="absolute inset-0"
                    initial={{ opacity: 0.4 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0.4 }}
                    transition={{ duration: 0.2 }}
                  >
                    {currentPhoto ? (
                      <img
                        src={currentPhoto.url}
                        alt={candidate.displayName}
                        className="w-full h-full object-cover"
                        draggable={false}
                      />
                    ) : (
                      <div
                        className="w-full h-full flex items-center justify-center text-9xl font-bold text-foreground/20"
                        style={{ background: placeholderBg }}
                      >
                        {candidate.displayName.charAt(0).toUpperCase()}
                      </div>
                    )}
                  </motion.div>
                </AnimatePresence>
              </motion.div>

              {/* Tap zones (only when multiple photos) */}
              {photoCount > 1 && (
                <>
                  <button
                    onClick={() => handleTapZone("left")}
                    className="absolute left-0 top-0 bottom-0 w-1/3 z-10"
                    aria-label="Previous photo"
                  />
                  <button
                    onClick={() => handleTapZone("right")}
                    className="absolute right-0 top-0 bottom-0 w-1/3 z-10"
                    aria-label="Next photo"
                  />
                </>
              )}

              {/* Progress bars (Instagram Story style) */}
              {photoCount > 1 && (
                <div className="absolute top-3 left-4 right-4 flex gap-1.5 z-20">
                  {displayPhotos.map((_, i) => (
                    <div
                      key={i}
                      className="h-[3px] flex-1 rounded-full bg-white/25 overflow-hidden"
                    >
                      <div
                        className={`h-full bg-white transition-all duration-300 ${
                          i < photoIndex ? "w-full" : i === photoIndex ? "w-full" : "w-0"
                        }`}
                      />
                    </div>
                  ))}
                </div>
              )}

              {/* Close button */}
              <button
                onClick={onClose}
                className="absolute top-4 right-4 w-10 h-10 rounded-full bg-black/50 backdrop-blur-md flex items-center justify-center text-white z-20"
              >
                <X size={20} weight="bold" />
              </button>

              {/* Seamless fade into content */}
              <div className="absolute bottom-0 left-0 right-0 h-32 bg-gradient-to-t from-background to-transparent pointer-events-none" />
            </div>

            {/* Content (overlaps hero via -mt for seamless feel) */}
            <div className="relative -mt-10 px-5 pb-32 space-y-4">
              {/* Name card */}
              <div>
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
              </div>

              {/* BaZi compatibility — big yin-yang + breakdown */}
              {(candidate.baziScore != null || candidate.reverseBaziScore != null) && (
                <div className="rounded-2xl p-5 bg-card/60 backdrop-blur-md border border-border/30 flex items-center gap-4">
                  <YinYangScore
                    forward={candidate.baziScore}
                    reverse={candidate.reverseBaziScore}
                    size="lg"
                  />
                  <div className="flex-1 space-y-2">
                    <p className="text-[10px] text-muted-foreground uppercase tracking-widest">BaZi Compatibility</p>
                    {candidate.baziScore != null && (
                      <div className="flex items-baseline gap-2">
                        <span className="text-lg font-semibold text-[#D4A056]">{candidate.baziScore}</span>
                        <span className="text-xs text-muted-foreground">them → you</span>
                      </div>
                    )}
                    {candidate.reverseBaziScore != null && (
                      <div className="flex items-baseline gap-2">
                        <span className="text-lg font-semibold text-foreground/80">{candidate.reverseBaziScore}</span>
                        <span className="text-xs text-muted-foreground">you → them</span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Bio */}
              {candidate.bio && (
                <div className="rounded-2xl p-5 bg-card/60 backdrop-blur-md border border-border/30">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-widest mb-2">About</p>
                  <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">{candidate.bio}</p>
                </div>
              )}

              {/* Interests */}
              {interests.length > 0 && (
                <div className="rounded-2xl p-5 bg-card/60 backdrop-blur-md border border-border/30">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-widest mb-3">Interests</p>
                  <div className="flex flex-wrap gap-2">
                    {interests.map((interest) => (
                      <span
                        key={interest}
                        className="rounded-full bg-primary/15 text-primary px-3 py-1.5 text-xs font-medium"
                      >
                        {interest}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Photo thumbs */}
              {photoCount > 1 && (
                <div className="rounded-2xl p-5 bg-card/60 backdrop-blur-md border border-border/30">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-widest mb-3">Photos</p>
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

            {/* Fixed bottom action bar */}
            {onSwipe && (
              <div className="fixed bottom-0 left-0 right-0 z-20 px-5 pt-3 pb-6 bg-gradient-to-t from-background via-background/95 to-transparent">
                <div className="flex gap-3 max-w-md mx-auto">
                  <button
                    onClick={() => { onSwipe("pass"); onClose(); }}
                    className="flex-1 h-13 py-3.5 rounded-2xl bg-card/80 backdrop-blur-md border border-border flex items-center justify-center gap-2 text-foreground/80 hover:bg-card active:scale-95 transition-all"
                  >
                    <X size={20} weight="bold" />
                    <span className="text-sm font-medium">Pass</span>
                  </button>
                  <button
                    onClick={() => { onSwipe("like"); onClose(); }}
                    className="flex-1 h-13 py-3.5 rounded-2xl bg-primary flex items-center justify-center gap-2 text-primary-foreground hover:bg-primary/90 active:scale-95 transition-all shadow-lg shadow-primary/30"
                  >
                    <Heart size={20} weight="fill" />
                    <span className="text-sm font-medium">Like</span>
                  </button>
                </div>
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
