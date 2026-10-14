"use client";

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useRef, useState } from "react";

import { tween, useCalm } from "@/lib/motion";

import { SwapText } from "./SwapText";

export function useToast() {
  const [message, setMessage] = useState<string | null>(null);
  const calm = useCalm();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const show = useCallback((m: string) => {
    setMessage(m);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(null), 3200);
  }, []);
  const node = (
    <AnimatePresence>
      {message && (
        <motion.div
          role="status"
          initial={{ transform: "translateY(12px) scale(0.96)", opacity: 0, filter: "blur(2px)" }}
          animate={{ transform: "translateY(0px) scale(1)", opacity: 1, filter: "blur(0px)", transition: calm(tween.reveal) }}
          exit={{ transform: "translateY(12px) scale(0.96)", opacity: 0, filter: "blur(2px)", transition: calm(tween.out) }}
          className="glass fixed inset-x-0 bottom-6 z-50 mx-auto w-fit max-w-[calc(100%-32px)] rounded-full px-5 py-2.5 text-[14px] shadow-[var(--shadow-lift)] ring-1 ring-hairline"
        >
          {/* A second message while one shows swaps in place instead of stacking a new toast. */}
          <SwapText text={message} />
        </motion.div>
      )}
    </AnimatePresence>
  );
  return { show, node };
}
