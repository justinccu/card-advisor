"use client";

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useRef, useState } from "react";

import { spring } from "@/lib/motion";

export function useToast() {
  const [message, setMessage] = useState<string | null>(null);
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
          initial={{ y: 40, opacity: 0, scale: 0.96 }}
          animate={{ y: 0, opacity: 1, scale: 1 }}
          exit={{ y: 40, opacity: 0, scale: 0.96 }}
          transition={spring.sheet}
          className="glass fixed inset-x-0 bottom-6 z-50 mx-auto w-fit max-w-[calc(100%-32px)] rounded-full px-5 py-2.5 text-[14px] shadow-[var(--shadow-lift)] ring-1 ring-hairline"
        >
          {message}
        </motion.div>
      )}
    </AnimatePresence>
  );
  return { show, node };
}
