"use client";

import { motion, useMotionTemplate, useMotionValue, useReducedMotion, useSpring, useTransform } from "motion/react";
import Image from "next/image";
import { useRef, useState } from "react";

import { type Face, type FaceText, cardFace } from "@/lib/cardFaces";
import { useCardImage } from "@/lib/cardImages";
import { useCardStyle } from "@/lib/cardStyle";
import { cardArt, issuerName } from "@/lib/issuers";
import { rubberBand, spring } from "@/lib/motion";

const MAX_TILT = 9; // degrees before the rubber band takes over

/**
 * The card's face: a simulated face in the card's own colors with its wordmarks as text
 * (lib/cardFaces). In `make demo` the viewer can switch to the local issuer card art ("real"),
 * which falls back to the simulated face when a card has no usable image or it fails to load.
 * Cards outside the catalog get an abstract, logo-free face. Tracks the pointer 1:1 while hovering or dragging (pointer
 * capture keeps tracking when the finger slides off), and springs home from wherever it is when
 * released — the return animation starts from the live value, so it's always interruptible.
 */
export function CardArt({
  cardId,
  issuerId,
  name,
  interactive = false,
  bare = false,
  className = "",
}: {
  /** catalog card id, for its card art; omit for cards not in the catalog */
  cardId?: string | null;
  issuerId: string;
  name: string;
  interactive?: boolean;
  /** thumbnails: art only, no text (a 64px card can't carry a legible name) */
  bare?: boolean;
  className?: string;
}) {
  const art = cardArt(issuerId, name);
  const [broken, setBroken] = useState(false);
  const style = useCardStyle();
  const realArt = useCardImage(cardId, style === "real");
  const image = broken ? null : realArt;
  const face = image ? null : cardFace(cardId);
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
          backgroundImage: image
            ? undefined
            : face
              ? `linear-gradient(135deg, ${face.stops.join(", ")})`
              : `linear-gradient(135deg, ${art.from}, ${art.to})`,
          boxShadow: "var(--shadow-lift)",
        }}
        className={`relative aspect-[1.586] w-full overflow-hidden rounded-[6%/9.5%] text-left ${face ? (face.ink === "light" ? "text-white" : "text-[#1d1d1f]") : inkClass} will-change-transform select-none ${interactive ? "touch-none" : ""}`}
        aria-hidden
      >
        {image && (
          <Image
            src={image}
            alt=""
            fill
            sizes="(max-width: 640px) 260px, 300px"
            draggable={false}
            onError={() => setBroken(true)}
            className="object-cover"
          />
        )}
        {face && <SimulatedFace face={face} />}
        {interactive && <motion.div className="pointer-events-none absolute inset-0" style={{ backgroundImage: glare }} />}
        <div className="absolute inset-0 bg-[linear-gradient(115deg,transparent_40%,rgba(255,255,255,0.12)_50%,transparent_60%)]" />
        {!image && !face && !bare && (
          <div className="absolute left-[7%] top-[9%] text-[clamp(9px,4.5cqw,13px)] font-semibold tracking-wide opacity-90">
            {issuerName(issuerId)}
          </div>
        )}
        {!image && !face && (
          <div className="absolute left-[7%] top-[36%] h-[17%] w-[13%] rounded-[18%] bg-gradient-to-br from-[#f6e3a1] to-[#c9a449] opacity-90" />
        )}
        {!image && !face && !bare && (
          <div className="absolute bottom-[9%] left-[7%] right-[7%] truncate text-[clamp(10px,5cqw,15px)] font-medium opacity-95">
            {name}
          </div>
        )}
      </motion.div>
    </div>
  );
}

const FONTS: Record<NonNullable<FaceText["f"]>, string> = {
  sans: "var(--font-sans)",
  serif: 'Georgia, "Times New Roman", serif',
  mono: '"SF Mono", Menlo, monospace',
};

/** A face laid out in the card's own coordinates. Portrait cards are drawn upright and turned
 *  sideways as a whole, the way their card art shows them. */
function SimulatedFace({ face }: { face: Face }) {
  const content = (
    <>
      <div
        className="absolute h-[17%] w-[13%] rounded-[18%] bg-gradient-to-br from-[#f6e3a1] to-[#c9a449] opacity-90"
        style={{ left: `${face.chip[0]}%`, top: `${face.chip[1]}%`, ...(face.vertical && { width: "17%", height: "13%" }) }}
      />
      {face.texts.map((t, i) => (
        <span
          key={i}
          className="absolute whitespace-nowrap leading-none"
          style={{
            top: `${t.y}%`,
            ...(t.a === "r" ? { right: `${100 - t.x}%` } : { left: `${t.x}%` }),
            transform: [t.a === "c" && "translateX(-50%)", t.rot && `rotate(${t.rot}deg)`].filter(Boolean).join(" ") || undefined,
            transformOrigin: t.a === "r" ? "right top" : "left top",
            fontSize: `${t.s}cqw`,
            fontWeight: t.w ?? 400,
            letterSpacing: t.tr ? `${t.tr}em` : undefined,
            fontFamily: FONTS[t.f ?? "sans"],
            fontStyle: t.i ? "italic" : undefined,
            opacity: t.o,
            color: t.c,
          }}
        >
          {t.t}
        </span>
      ))}
    </>
  );
  if (!face.vertical) return content;
  // Portrait box (63.05% x 158.6% of the landscape card), centered and turned a quarter left.
  return (
    <div className="absolute left-1/2 top-1/2 h-[158.6%] w-[63.05%] -translate-x-1/2 -translate-y-1/2 -rotate-90">
      {content}
    </div>
  );
}
