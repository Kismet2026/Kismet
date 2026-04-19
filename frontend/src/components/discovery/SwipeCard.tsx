"use client";

import { motion, useMotionValue, useTransform, type PanInfo } from "framer-motion";
import { Heart, X } from "@phosphor-icons/react";
import { YinYangScore } from "./YinYangScore";
import type { Candidate } from "@/types";

interface SwipeCardProps {
  candidate: Candidate;
  onSwipe: (action: "like" | "pass") => void;
  onTap?: () => void;
  isTop: boolean;
}

const SWIPE_THRESHOLD = 100;

export function SwipeCard({ candidate, onSwipe, onTap, isTop }: SwipeCardProps) {
  const dragStartRef = { x: 0, y: 0 };
  const x = useMotionValue(0);
  const rotate = useTransform(x, [-200, 200], [-15, 15]);
  const likeOpacity = useTransform(x, [0, 80], [0, 1]);
  const passOpacity = useTransform(x, [-80, 0], [1, 0]);

  function handleDragStart(_: unknown, info: PanInfo) {
    dragStartRef.x = info.point.x;
    dragStartRef.y = info.point.y;
  }

  function handleDragEnd(_: unknown, info: PanInfo) {
    const dx = Math.abs(info.offset.x);
    const dy = Math.abs(info.offset.y);
    if (dx < 30 && dy < 30 && onTap) {
      onTap();
      return;
    }
    if (info.offset.x > SWIPE_THRESHOLD) {
      onSwipe("like");
    } else if (info.offset.x < -SWIPE_THRESHOLD) {
      onSwipe("pass");
    }
  }

  const placeholderBg = `hsl(${candidate.userId.charCodeAt(0) * 7 % 360}, 25%, 20%)`;

  return (
    <motion.div
      className="absolute inset-0 touch-none"
      style={{
        x: isTop ? x : 0,
        rotate: isTop ? rotate : 0,
        zIndex: isTop ? 10 : 5,
        scale: isTop ? 1 : 0.95,
      }}
      drag={isTop ? "x" : false}
      dragConstraints={{ left: 0, right: 0 }}
      dragElastic={0.8}
      onDragStart={isTop ? handleDragStart : undefined}
      onDragEnd={isTop ? handleDragEnd : undefined}
      exit={{
        x: x.get() > 0 ? 300 : -300,
        opacity: 0,
        transition: { duration: 0.3 },
      }}
    >
      <div className="relative w-full h-full rounded-2xl overflow-hidden shadow-2xl border border-border/30">
        {/* Photo / placeholder */}
        {candidate.avatarUrl ? (
          <img
            src={candidate.avatarUrl}
            alt={candidate.displayName}
            className="w-full h-full object-cover"
            draggable={false}
          />
        ) : (
          <div
            className="w-full h-full flex items-center justify-center text-6xl font-bold text-foreground/20"
            style={{ background: placeholderBg }}
          >
            {candidate.displayName.charAt(0).toUpperCase()}
          </div>
        )}

        {/* Gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />

        {/* Like indicator */}
        {isTop && (
          <motion.div
            className="absolute top-8 left-6 rounded-xl border-4 border-green-400 px-4 py-2 -rotate-12"
            style={{ opacity: likeOpacity }}
          >
            <span className="text-green-400 text-2xl font-bold tracking-wide">LIKE</span>
          </motion.div>
        )}

        {/* Pass indicator */}
        {isTop && (
          <motion.div
            className="absolute top-8 right-6 rounded-xl border-4 border-red-400 px-4 py-2 rotate-12"
            style={{ opacity: passOpacity }}
          >
            <span className="text-red-400 text-2xl font-bold tracking-wide">NOPE</span>
          </motion.div>
        )}

        {/* BaZi yin-yang compatibility — outer=forward, inner=reverse */}
        {(candidate.baziScore != null || candidate.reverseBaziScore != null) && (
          <div className="absolute top-4 right-4">
            <YinYangScore
              forward={candidate.baziScore}
              reverse={candidate.reverseBaziScore}
              size="md"
            />
          </div>
        )}

        {/* Info overlay */}
        <div className="absolute bottom-0 left-0 right-0 p-5">
          <h2 className="text-2xl font-bold text-white">
            {candidate.displayName}
            {candidate.age && (
              <span className="font-normal text-white/70">, {candidate.age}</span>
            )}
          </h2>
          {candidate.city && (
            <p className="text-sm text-white/60 mt-0.5">{candidate.city}</p>
          )}
          {candidate.bio && (
            <p className="text-sm text-white/80 mt-2 line-clamp-2">{candidate.bio}</p>
          )}
          {isTop && (
            <p className="text-xs text-white/40 mt-2">Tap for details</p>
          )}

          {/* Inline action buttons */}
          {isTop && (
            <div className="flex gap-3 mt-4">
              <button
                onClick={(e) => { e.stopPropagation(); onSwipe("pass"); }}
                className="flex-1 h-11 rounded-xl bg-white/10 backdrop-blur-sm flex items-center justify-center gap-2 text-white/80 hover:bg-white/20 active:scale-95 transition-all"
              >
                <X size={20} weight="bold" />
                <span className="text-sm font-medium">Pass</span>
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onSwipe("like"); }}
                className="flex-1 h-11 rounded-xl bg-primary/80 backdrop-blur-sm flex items-center justify-center gap-2 text-primary-foreground hover:bg-primary active:scale-95 transition-all"
              >
                <Heart size={20} weight="fill" />
                <span className="text-sm font-medium">Like</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}
