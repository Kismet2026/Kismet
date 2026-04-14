"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkle, ArrowRight } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";

// Floating particle component
function Particle({ delay, x, y, size }: { delay: number; x: number; y: number; size: number }) {
  return (
    <motion.div
      className="absolute rounded-full bg-primary/20"
      style={{ width: size, height: size, left: `${x}%`, top: `${y}%` }}
      initial={{ opacity: 0, scale: 0 }}
      animate={{
        opacity: [0, 0.6, 0],
        scale: [0, 1, 0.5],
        y: [0, -80, -160],
      }}
      transition={{
        duration: 4,
        delay,
        repeat: Infinity,
        ease: "easeOut",
      }}
    />
  );
}

// Orbiting ring around the logo
function OrbitRing({ radius, duration, dotSize }: { radius: number; duration: number; dotSize: number }) {
  return (
    <motion.div
      className="absolute"
      style={{ width: radius * 2, height: radius * 2, left: `calc(50% - ${radius}px)`, top: `calc(50% - ${radius}px)` }}
      animate={{ rotate: 360 }}
      transition={{ duration, repeat: Infinity, ease: "linear" }}
    >
      <div
        className="absolute rounded-full bg-primary"
        style={{ width: dotSize, height: dotSize, top: 0, left: `calc(50% - ${dotSize / 2}px)` }}
      />
    </motion.div>
  );
}

const particles = Array.from({ length: 12 }, (_, i) => ({
  id: i,
  delay: i * 0.5,
  x: 15 + Math.random() * 70,
  y: 20 + Math.random() * 60,
  size: 4 + Math.random() * 6,
}));

const taglines = [
  "Written in the stars",
  "Destined by BaZi",
  "Your fate awaits",
];

export default function Home() {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const [taglineIndex, setTaglineIndex] = useState(0);

  // Auto-redirect for logged-in users
  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace("/discover");
    }
  }, [isAuthenticated, isLoading, router]);

  // Rotate taglines
  useEffect(() => {
    const interval = setInterval(() => {
      setTaglineIndex((prev) => (prev + 1) % taglines.length);
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  if (isLoading) return null;
  if (isAuthenticated) return null;

  return (
    <div className="min-h-dvh flex flex-col items-center justify-center px-6 overflow-hidden relative">
      {/* Floating particles */}
      {particles.map((p) => (
        <Particle key={p.id} delay={p.delay} x={p.x} y={p.y} size={p.size} />
      ))}

      {/* Ambient glow */}
      <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[300px] h-[300px] rounded-full bg-primary/5 blur-[100px]" />

      {/* Logo with orbit */}
      <motion.div
        className="relative mb-8"
        initial={{ opacity: 0, scale: 0.5 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
      >
        <div className="relative w-24 h-24 flex items-center justify-center">
          <OrbitRing radius={48} duration={8} dotSize={6} />
          <OrbitRing radius={40} duration={6} dotSize={4} />
          <motion.div
            className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center border border-primary/20"
            animate={{ boxShadow: ["0 0 20px rgba(212,160,86,0.1)", "0 0 40px rgba(212,160,86,0.2)", "0 0 20px rgba(212,160,86,0.1)"] }}
            transition={{ duration: 3, repeat: Infinity }}
          >
            <Sparkle size={32} className="text-primary" weight="fill" />
          </motion.div>
        </div>
      </motion.div>

      {/* Title */}
      <motion.h1
        className="text-5xl font-bold mb-3 tracking-tight"
        style={{ fontFamily: "var(--font-script)" }}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3, duration: 0.6 }}
      >
        Kismet
      </motion.h1>

      {/* Rotating tagline */}
      <div className="h-8 mb-10 relative overflow-hidden">
        <AnimatePresence mode="wait">
          <motion.p
            key={taglineIndex}
            className="text-muted-foreground text-base absolute w-full text-center"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.4 }}
          >
            {taglines[taglineIndex]}
          </motion.p>
        </AnimatePresence>
      </div>

      {/* CTA buttons */}
      <motion.div
        className="flex flex-col gap-3 w-full max-w-xs"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.6, duration: 0.6 }}
      >
        <Button
          onClick={() => router.push("/signup")}
          className="w-full h-12 text-base gap-2 group"
        >
          Get Started
          <ArrowRight
            size={18}
            className="transition-transform group-hover:translate-x-1"
          />
        </Button>
        <button
          onClick={() => router.push("/login")}
          className="w-full h-12 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          Already have an account? <span className="text-primary">Log in</span>
        </button>
      </motion.div>

      {/* Bottom decoration */}
      <motion.div
        className="absolute bottom-8 flex gap-1.5"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1, duration: 0.8 }}
      >
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-primary/40"
            animate={{ opacity: [0.3, 1, 0.3] }}
            transition={{ duration: 2, delay: i * 0.3, repeat: Infinity }}
          />
        ))}
      </motion.div>
    </div>
  );
}
