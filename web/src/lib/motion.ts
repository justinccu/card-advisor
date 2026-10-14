import { useReducedMotion, type Transition } from "motion/react";

// Spring presets in Apple's terms. Motion's `visualDuration` ≈ UIKit `response`; `bounce` maps
// from damping ratio (bounce 0 = critically damped, damping 1.0).
export const spring = {
  // Navigation / reposition: damping 1.0, response 0.4s — no overshoot.
  nav: { type: "spring", visualDuration: 0.4, bounce: 0 },
  // Sheets & drawers: damping ~0.82, response 0.32s — only a hint of bounce.
  sheet: { type: "spring", visualDuration: 0.32, bounce: 0.18 },
  // Buttons, toggles, chips: damping 0.7, response 0.2s — playful.
  micro: { type: "spring", visualDuration: 0.2, bounce: 0.3 },
} satisfies Record<string, Transition>;

// The CSS motion tokens (globals.css) for Motion components that enter and leave. Motion runs
// opacity, filter and a full `transform` string off the main thread; its x / y / scale
// shorthands run on it (they still suit gestures and `layout` elements, which need them).
const enter = [0.23, 1, 0.32, 1] as const;
export const tween = {
  /** text and icon swaps */
  swap: { duration: 0.15, ease: "easeInOut" },
  /** something leaving */
  out: { duration: 0.15, ease: enter },
  /** small things appearing */
  in: { duration: 0.2, ease: enter },
  /** panels and reveals */
  reveal: { duration: 0.25, ease: enter },
} satisfies Record<string, Transition>;
export const STAGGER = 0.04;

/** Motion's reducedMotion="user" stills only its x / y / scale shorthands, not a `transform`
 *  string; this stills those too (the move is instant, the fade stays). */
export function useCalm(): (t: Transition) => Transition {
  const reduce = useReducedMotion();
  return (t) => (reduce ? { ...t, transform: { duration: 0 } } : t);
}
/** Changes that follow typing: no animation (they'd lag behind the keyboard). */
export const INSTANT = { duration: 0 } satisfies Transition;

// Pressed state is applied on pointerdown (Motion's whileTap), never on click.
export const press = { scale: 0.97 };

/** iOS-style rubber band: resistance grows with distance, never a hard stop.
 *  f(x) = (x * d) / (d + x), applied symmetrically to overscroll `x` with dimension `d`. */
export function rubberBand(x: number, d: number): number {
  const sign = Math.sign(x);
  const ax = Math.abs(x);
  return (sign * (ax * d)) / (d + ax);
}

/** Where a flick would come to rest (UIScrollView deceleration projection). */
export function project(velocity: number, decelerationRate = 0.998): number {
  return ((velocity / 1000) * decelerationRate) / (1 - decelerationRate);
}
