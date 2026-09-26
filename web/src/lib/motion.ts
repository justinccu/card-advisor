import type { Transition } from "motion/react";

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
