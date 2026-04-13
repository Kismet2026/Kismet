"use client";

import { motion, AnimatePresence } from "framer-motion";
import { Heart, ChatCircle, ArrowRight } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { Candidate } from "@/types";

interface MatchModalProps {
  isOpen: boolean;
  candidate: Candidate | null;
  matchId: string | null;
  onChat: () => void;
  onContinue: () => void;
}

export function MatchModal({ isOpen, candidate, onChat, onContinue }: MatchModalProps) {
  if (!candidate) return null;

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center px-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />

          {/* Content */}
          <motion.div
            className="relative z-10 flex flex-col items-center text-center max-w-sm w-full"
            initial={{ scale: 0.5, y: 40 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.8, opacity: 0 }}
            transition={{ type: "spring", damping: 20, stiffness: 300 }}
          >
            {/* Celebration hearts */}
            {[...Array(6)].map((_, i) => (
              <motion.div
                key={i}
                className="absolute text-primary"
                initial={{ opacity: 0, scale: 0 }}
                animate={{
                  opacity: [0, 1, 0],
                  scale: [0, 1.5, 0],
                  x: Math.cos((i / 6) * Math.PI * 2) * 120,
                  y: Math.sin((i / 6) * Math.PI * 2) * 120 - 40,
                }}
                transition={{ duration: 1.5, delay: i * 0.1, ease: "easeOut" }}
              >
                <Heart size={24} weight="fill" />
              </motion.div>
            ))}

            {/* Avatar */}
            <motion.div
              className="w-28 h-28 rounded-full overflow-hidden border-4 border-primary shadow-xl shadow-primary/20 mb-6"
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ type: "spring", delay: 0.2 }}
            >
              {candidate.avatarUrl ? (
                <img
                  src={candidate.avatarUrl}
                  alt={candidate.displayName}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="w-full h-full bg-card flex items-center justify-center text-3xl font-bold text-muted-foreground">
                  {candidate.displayName.charAt(0)}
                </div>
              )}
            </motion.div>

            <motion.h2
              className="text-3xl font-bold text-foreground mb-2"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
            >
              It&apos;s a Match!
            </motion.h2>

            <motion.p
              className="text-muted-foreground mb-8"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.4 }}
            >
              You and {candidate.displayName} liked each other
            </motion.p>

            <motion.div
              className="flex flex-col gap-3 w-full"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.5 }}
            >
              <Button onClick={onChat} className="w-full h-12 gap-2 text-base">
                <ChatCircle size={20} weight="fill" />
                Send a Message
              </Button>
              <button
                onClick={onContinue}
                className="flex items-center justify-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors py-3"
              >
                Keep Swiping <ArrowRight size={16} />
              </button>
            </motion.div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
