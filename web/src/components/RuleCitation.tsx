"use client";

import { BookOpen } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";

import { tween, useCalm } from "@/lib/motion";
import type { RuleFacts } from "@/lib/types";

const SHOW_AFTER = 150; // ms: long enough that passing over a label doesn't open it
const HIDE_AFTER = 120; // ms: time to move the pointer from the label onto the card
const WIDTH = 320;

const noop = () => () => {};
const useMounted = () => useSyncExternalStore(noop, () => true, () => false);

type Place = { left: number; top?: number; bottom?: number };

function sourceLine(rule: RuleFacts): string {
  // An official rule whose bank page we haven't linked yet: say so plainly, not "not on the
  // bank's website" (the terms are the bank's).
  const where =
    rule.issuer_link || !rule.source.startsWith("the issuer's own terms")
      ? rule.source
      : "the issuer's own terms (the bank's page isn't linked yet)";
  return `Source: ${where}. Checked ${rule.verified_on}.`;
}

/** A cited issuer rule. Its explanation opens in a card on hover, focus or tap (the browser's own
 *  title tooltip took a second of holding still and never showed on touch). It links only to the
 *  rule on its own bank's website; a rule the bank doesn't publish (Chase 5/24) is a button that
 *  just opens the card. */
export function RuleCitation({ rule, children }: { rule: RuleFacts; children: React.ReactNode }) {
  const id = useId();
  const anchor = useRef<HTMLElement | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const [place, setPlace] = useState<Place | null>(null);
  const mounted = useMounted();
  const calm = useCalm();

  const show = () => {
    const r = anchor.current?.getBoundingClientRect();
    if (!r) return;
    const left = Math.max(8, Math.min(r.left, window.innerWidth - WIDTH - 8));
    // Below the label when there's room, otherwise above it.
    setPlace(r.bottom + 220 < window.innerHeight ? { left, top: r.bottom + 6 } : { left, bottom: window.innerHeight - r.top + 6 });
  };
  const later = (fn: () => void, ms: number) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(fn, ms);
  };
  const hide = () => setPlace(null);

  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => {
    if (!place) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && hide();
    window.addEventListener("scroll", hide, true); // the chat scrolled away from the label
    window.addEventListener("resize", hide);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
      window.removeEventListener("keydown", onKey);
    };
  }, [place]);

  const triggers = {
    "data-rule": rule.rule_id,
    "aria-describedby": place ? id : undefined,
    onMouseEnter: () => later(show, SHOW_AFTER),
    onMouseLeave: () => later(hide, HIDE_AFTER),
    onFocus: () => later(show, 0),
    onBlur: () => later(hide, 0),
  };
  const chip =
    "inline-flex items-center gap-1 rounded-md bg-tile px-1.5 py-px align-baseline text-[13px] text-ink-2 transition-colors duration-(--dur-quick) hover:bg-black/[0.07] hover:text-ink dark:hover:bg-white/15";
  const label = (
    <>
      <BookOpen size={12} aria-hidden />
      {children}
    </>
  );

  return (
    <>
      {rule.issuer_link ? (
        <a
          ref={(el) => {
            anchor.current = el;
          }}
          href={rule.issuer_link}
          target="_blank"
          rel="noopener noreferrer"
          className={chip}
          {...triggers}
        >
          {label}
        </a>
      ) : (
        <button
          ref={(el) => {
            anchor.current = el;
          }}
          type="button"
          aria-expanded={!!place}
          onClick={() => (place ? hide() : show())}
          className={`${chip} cursor-help`}
          {...triggers}
        >
          {label}
        </button>
      )}
      {mounted &&
        createPortal(
          <AnimatePresence>
            {place && (
              <motion.div
                id={id}
                role="tooltip"
                onMouseEnter={() => window.clearTimeout(timer.current)}
                onMouseLeave={() => later(hide, HIDE_AFTER)}
                initial={{ opacity: 0, transform: "scale(0.97)" }}
                animate={{ opacity: 1, transform: "scale(1)", transition: calm(tween.in) }}
                exit={{ opacity: 0, transform: "scale(0.97)", transition: calm(tween.out) }}
                style={{ ...place, width: WIDTH, transformOrigin: place.top !== undefined ? "top left" : "bottom left" }}
                className="fixed z-[60] rounded-xl bg-surface p-3 text-left shadow-[var(--shadow-lift)] ring-1 ring-hairline"
              >
                <p className="text-[13px] font-semibold leading-snug text-ink">{rule.summary}</p>
                {rule.how_it_counts.length > 0 && (
                  <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-[12px] leading-snug text-ink-2">
                    {rule.how_it_counts.slice(0, 3).map((fact) => (
                      <li key={fact}>{fact}</li>
                    ))}
                  </ul>
                )}
                <p className="mt-2 text-[11px] text-ink-3">{sourceLine(rule)}</p>
                {rule.issuer_link && <p className="mt-0.5 text-[11px] text-link">Opens the bank&apos;s page ↗</p>}
              </motion.div>
            )}
          </AnimatePresence>,
          document.body,
        )}
    </>
  );
}
