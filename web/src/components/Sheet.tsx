"use client";

import { AnimatePresence, motion, useDragControls, useReducedMotion, type PanInfo } from "motion/react";
import { X } from "lucide-react";
import { useEffect, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";

import { press, project, spring, tween, useCalm } from "@/lib/motion";

const noop = () => () => {};
/** false during SSR and hydration, true after: portals must not render before hydration. */
const useMounted = () => useSyncExternalStore(noop, () => true, () => false);

// Tailwind's `sm`, where the sheet becomes a centered panel.
const WIDE = "(min-width: 640px)";
const useWide = () =>
  useSyncExternalStore(
    (onChange) => {
      const query = window.matchMedia(WIDE);
      query.addEventListener("change", onChange);
      return () => query.removeEventListener("change", onChange);
    },
    () => window.matchMedia(WIDE).matches,
    () => false,
  );

const DISMISS_DISTANCE = 140; // px, or…
const DISMISS_PROJECTION = 260; // …where a flick would come to rest

/**
 * Bottom sheet on phones, centered panel on wider screens. The panel scales up from 96% and fades
 * (a dialog with no anchor grows in place; sliding it up from the screen's bottom edge left it
 * lingering there). The phone sheet slides up and, on touch, follows the finger 1:1
 * from the grabber, rubber-bands when pulled up past its resting place (Motion's dragElastic is
 * the (x·d)/(d+x) resistance curve), and on release projects the flick's momentum: far enough ->
 * dismiss carrying the finger's velocity, otherwise spring back from wherever it was released.
 */
export function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  const drag = useDragControls();
  const reduce = useReducedMotion();
  const mounted = useMounted();
  const wide = useWide();
  const calm = useCalm();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // A real modal: everything behind the sheet leaves the tab order and accessibility tree.
    const background = [...document.querySelectorAll<HTMLElement>("body > header, body > main, body > footer, body > div:not([data-sheet])")];
    background.forEach((el) => el.setAttribute("inert", ""));
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      background.forEach((el) => el.removeAttribute("inert"));
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  const onDragEnd = (_: unknown, info: PanInfo) => {
    const resting = info.offset.y + project(info.velocity.y);
    if (info.offset.y > DISMISS_DISTANCE || resting > DISMISS_PROJECTION) onClose();
  };

  if (!mounted) return null;
  return createPortal(
    <AnimatePresence>
      {open && (
        <div data-sheet className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal aria-label={title}>
          <motion.button
            aria-label="Close"
            className="absolute inset-0 bg-black/30 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1, transition: tween.reveal }}
            exit={{ opacity: 0, transition: tween.out }}
            onClick={onClose}
          />
          <motion.section
            drag={reduce || wide ? false : "y"}
            dragListener={false}
            dragControls={drag}
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0.08, bottom: 1 }}
            onDragEnd={onDragEnd}
            {...(wide
              ? {
                  initial: { opacity: 0, transform: "scale(0.96)" },
                  animate: { opacity: 1, transform: "scale(1)", transition: calm(tween.reveal) },
                  exit: { opacity: 0, transform: "scale(0.96)", transition: calm(tween.out) },
                }
              : { initial: { y: "100%" }, animate: { y: 0 }, exit: { y: "100%" }, transition: spring.sheet })}
            className="relative max-h-[88dvh] w-full overflow-hidden rounded-t-[28px] bg-surface shadow-[var(--shadow-lift)] will-change-transform sm:max-w-[640px] sm:rounded-[28px]"
          >
            <div
              // The grabber drags the phone sheet only; the wide panel keeps its spacing, not its look.
              className="flex cursor-grab touch-none justify-center pb-1 pt-2.5 active:cursor-grabbing sm:invisible"
              onPointerDown={(e) => drag.start(e)}
            >
              <span className="h-[5px] w-9 rounded-full bg-black/20 dark:bg-white/25" aria-hidden />
            </div>
            <motion.button
              whileTap={press}
              transition={spring.micro}
              onClick={onClose}
              aria-label="Close"
              className="absolute right-4 top-4 z-10 grid size-8 place-items-center rounded-full bg-black/[0.06] text-ink-2 dark:bg-white/10"
            >
              <X size={16} />
            </motion.button>
            <div className="max-h-[calc(88dvh-24px)] overflow-y-auto overscroll-contain px-6 pb-8 pt-2">
              {children}
            </div>
          </motion.section>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
