"use client";

import { motion, useMotionTemplate, useMotionValue, useReducedMotion, useSpring, useTransform } from "motion/react";
import { useRef } from "react";

import { cardArt, issuerName } from "@/lib/issuers";
import { rubberBand, spring } from "@/lib/motion";

const MAX_TILT = 9; // degrees before the rubber band takes over

/**
 * An abstract, logo-free card face. Tracks the pointer 1:1 while hovering or dragging (pointer
 * capture keeps tracking when the finger slides off), and springs home from wherever it is when
 * released — the return animation starts from the live value, so it's always interruptible.
 */
export function CardArt({
  issuerId,
  name,
  interactive = false,
  bare = false,
  className = "",
}: {
  issuerId: string;
  name: string;
  interactive?: boolean;
  /** thumbnails: art only, no text (a 64px card can't carry a legible name) */
  bare?: boolean;
  className?: string;
}) {
  const art = cardArt(issuerId, name);
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const px = useMotionValue(0); // -1..1 across the card, can overshoot while captured
  const py = useMotionValue(0);
  const rx = useSpring(useTransform(py, (v) => -rubberBand(v * MAX_TILT, MAX_TILT * 1.5)), spring.micro);
  const ry = useSpring(useTransform(px, (v) => rubberBand(v * MAX_TILT, MAX_TILT * 1.5)), spring.micro);
  const glareX = useTransform(px, [-1, 1], ["15%", "85%"]);
  const glareY = useTransform(py, [-1, 1], ["10%", "90%"]);
  const glare = useMotionTemplate`radial-gradient(circle at ${glareX} ${glareY}, rgba(255,255,255,0.35), transparent 55%)`;

  const track = (e: React.PointerEvent) => {
    if (!interactive || reduce || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    px.set(((e.clientX - r.left) / r.width) * 2 - 1);
    py.set(((e.clientY - r.top) / r.height) * 2 - 1);
  };
  const release = () => {
    px.set(0);
    py.set(0);
  };

  const inkClass = art.ink === "light" ? "text-white" : "text-[#1d1d1f]";

  return (
    <div className={`[perspective:900px] [container-type:inline-size] ${className}`}>
      <motion.div
        ref={ref}
        onPointerMove={track}
        onPointerDown={(e) => {
          if (interactive && e.pointerType !== "mouse") e.currentTarget.setPointerCapture(e.pointerId);
          track(e);
        }}
        onPointerUp={release}
        onPointerLeave={release}
        onPointerCancel={release}
        style={{
          rotateX: interactive ? rx : 0,
          rotateY: interactive ? ry : 0,
          backgroundImage: `linear-gradient(135deg, ${art.from}, ${art.to})`,
          boxShadow: "var(--shadow-lift)",
        }}
        className={`relative aspect-[1.586] w-full overflow-hidden rounded-[6%/9.5%] text-left ${inkClass} will-change-transform select-none ${interactive ? "touch-none" : ""}`}
        aria-hidden
      >
        {interactive && <motion.div className="pointer-events-none absolute inset-0" style={{ backgroundImage: glare }} />}
        <div className="absolute inset-0 bg-[linear-gradient(115deg,transparent_40%,rgba(255,255,255,0.12)_50%,transparent_60%)]" />
        {!bare && (
          <div className="absolute left-[7%] top-[9%] text-[clamp(9px,4.5cqw,13px)] font-semibold tracking-wide opacity-90">
            {issuerName(issuerId)}
          </div>
        )}
        <div className="absolute left-[7%] top-[36%] h-[17%] w-[13%] rounded-[18%] bg-gradient-to-br from-[#f6e3a1] to-[#c9a449] opacity-90" />
        {!bare && (
          <div className="absolute bottom-[9%] left-[7%] right-[7%] truncate text-[clamp(10px,5cqw,15px)] font-medium opacity-95">
            {name}
          </div>
        )}
      </motion.div>
    </div>
  );
}
