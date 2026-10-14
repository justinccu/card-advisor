"use client";

import { AnimatePresence, motion, useIsPresent } from "motion/react";

import { tween, useCalm } from "@/lib/motion";

/** Text that changes in place: the old line leaves upward through a small blur while the new one
 *  rises in, both at once in the same grid cell (transitions.dev's text-states swap). */
export function SwapText({ text, className = "" }: { text: string; className?: string }) {
  return (
    <span className="inline-grid">
      <AnimatePresence initial={false}>
        <Line key={text} text={text} className={className} />
      </AnimatePresence>
    </span>
  );
}

function Line({ text, className }: { text: string; className: string }) {
  const calm = useCalm();
  // The leaving copy is hidden from screen readers, so a live region reads only the new text.
  const present = useIsPresent();
  return (
    <motion.span
      aria-hidden={present ? undefined : true}
      initial={{ opacity: 0, transform: "translateY(4px)", filter: "blur(2px)" }}
      animate={{ opacity: 1, transform: "translateY(0px)", filter: "blur(0px)" }}
      exit={{ opacity: 0, transform: "translateY(-4px)", filter: "blur(2px)" }}
      transition={calm(tween.swap)}
      className={`[grid-area:1/1] ${className}`}
    >
      {text}
    </motion.span>
  );
}
