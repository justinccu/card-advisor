"use client";

import {
  animate,
  motion,
  useMotionValue,
  useReducedMotion,
  useTransform,
  type AnimationPlaybackControls,
  type MotionValue,
  type PanInfo,
} from "motion/react";
import { useRef, useState } from "react";

import { project, rubberBand, spring } from "@/lib/motion";
import type { CatalogCard } from "@/lib/types";

import { CardArt } from "./CardArt";

const SLOT = 220; // px between resting positions

/**
 * A fanned deck you can fling.
 * - Pointer down stops any running spring and grabs the deck from its *live* position
 *   (interruptible: catching it mid-flight never jumps).
 * - While dragging, x follows the finger 1:1; past either end it rubber-bands, (x·d)/(d+x).
 * - On release the flick's momentum is projected to pick the snap target, and the finger's
 *   velocity is handed to the spring so motion continues without a seam.
 */
export function HeroDeck({ cards }: { cards: CatalogCard[] }) {
  const reduce = useReducedMotion();
  const [index, setIndex] = useState(Math.floor(cards.length / 2));
  const x = useMotionValue(-index * SLOT);
  const base = useRef(0);
  const running = useRef<AnimationPlaybackControls | null>(null);
  const moved = useRef(false); // a drag must not also "click" the card under the finger
  const minX = -(cards.length - 1) * SLOT;

  const snapTo = (i: number, velocity = 0) => {
    const next = Math.max(0, Math.min(cards.length - 1, i));
    setIndex(next);
    running.current?.stop();
    running.current = reduce
      ? (x.set(-next * SLOT), null)
      : animate(x, -next * SLOT, { ...spring.sheet, velocity });
  };

  const onPanStart = () => {
    running.current?.stop(); // catch it mid-air
    base.current = x.get();
  };

  const onPan = (_: PointerEvent, info: PanInfo) => {
    if (Math.abs(info.offset.x) > 6) moved.current = true;
    const raw = base.current + info.offset.x;
    const over = raw > 0 ? raw : raw < minX ? raw - minX : 0;
    x.set(over ? raw - over + rubberBand(over, SLOT) : raw);
  };

  const onPanEnd = (_: PointerEvent, info: PanInfo) => {
    const resting = x.get() + project(info.velocity.x);
    snapTo(Math.round(-resting / SLOT), info.velocity.x);
  };

  return (
    <div className="relative h-[260px] w-full overflow-hidden sm:h-[300px]" role="region" aria-label="Featured cards">
      <motion.div
        className="absolute inset-0 cursor-grab touch-pan-y active:cursor-grabbing"
        onPanStart={reduce ? undefined : onPanStart}
        onPan={reduce ? undefined : onPan}
        onPanEnd={reduce ? undefined : onPanEnd}
        onPointerDown={() => {
          running.current?.stop();
          moved.current = false;
        }}
      >
        <motion.div className="absolute left-1/2 top-[45%] h-0 w-0" style={{ x }}>
          {cards.map((c, i) => (
            <DeckCard key={c.id} card={c} i={i} x={x} onSelect={() => !moved.current && snapTo(i)} />
          ))}
        </motion.div>
      </motion.div>
      <div className="absolute bottom-2 left-1/2 flex -translate-x-1/2 gap-1.5" role="tablist" aria-label="Choose card">
        {cards.map((c, i) => (
          <button
            key={c.id}
            role="tab"
            aria-selected={i === index}
            aria-label={c.name}
            onClick={() => snapTo(i)}
            className={`h-1.5 rounded-full transition-[width,background-color] duration-300 ${i === index ? "w-5 bg-ink" : "w-1.5 bg-ink-3/50"}`}
          />
        ))}
      </div>
    </div>
  );
}

function DeckCard({
  card,
  i,
  x,
  onSelect,
}: {
  card: CatalogCard;
  i: number;
  x: MotionValue<number>;
  onSelect: () => void;
}) {
  // Distance from center (in slots) drives scale, tilt, fade and stacking, derived from the live
  // x on every frame, so the fan responds continuously rather than only when a snap completes.
  const d = useTransform(x, (v) => (v + i * SLOT) / SLOT);
  const scale = useTransform(d, [-2, 0, 2], [0.78, 1, 0.78]);
  const rotate = useTransform(d, [-2, 0, 2], [-8, 0, 8]);
  // Opaque while visible: translucent cards overlapping each other would be glass on glass.
  const opacity = useTransform(d, [-2.6, -2.1, 2.1, 2.6], [0, 1, 1, 0]);
  const brightness = useTransform(d, [-2, 0, 2], [0.82, 1, 0.82]);
  const filter = useTransform(brightness, (b) => `brightness(${b})`);
  const zIndex = useTransform(d, (v) => 100 - Math.round(Math.abs(v) * 10));
  return (
    <motion.button
      type="button"
      onClick={onSelect}
      aria-label={card.name}
      className="absolute w-[260px] sm:w-[300px]"
      style={{ left: i * SLOT, x: "-50%", y: "-50%", scale, rotate, opacity, zIndex, filter }}
    >
      <CardArt issuerId={card.issuer_id} name={card.name} />
    </motion.button>
  );
}
