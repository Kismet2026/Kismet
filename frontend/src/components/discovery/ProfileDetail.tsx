"use client";

import { motion, AnimatePresence } from "framer-motion";
import { X, MapPin } from "@phosphor-icons/react";
import { BaziScoreBadge } from "./BaziScoreBadge";
import type { Candidate } from "@/types";

interface ProfileDetailProps {
  candidate: Candidate | null;
  isOpen: boolean;
  onClose: () => void;
}

export function ProfileDetail({ candidate, isOpen, onClose }: ProfileDetailProps) {
  if (!candidate) return null;

  const placeholderBg = `hsl(${candidate.userId.charCodeAt(0) * 7 % 360}, 25%, 20%)`;

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
            {/* Header image */}
            <div className="relative h-[50dvh]">
              {candidate.avatarUrl ? (
                <img
                  src={candidate.avatarUrl}
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
              <div className="absolute inset-0 bg-gradient-to-t from-background via-transparent to-transparent" />

              {/* Close button */}
              <button
                onClick={onClose}
                className="absolute top-4 right-4 w-10 h-10 rounded-full bg-black/50 flex items-center justify-center text-white"
              >
                <X size={20} weight="bold" />
              </button>

              {/* BaZi badge */}
              <div className="absolute top-4 left-4">
                <BaziScoreBadge score={candidate.baziScore} size="md" />
              </div>
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
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
