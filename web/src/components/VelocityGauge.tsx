"use client";

import { animate, motion, useMotionValue, useTransform } from "motion/react";
import { useEffect } from "react";

import { shortDate } from "@/lib/format";
import { spring } from "@/lib/motion";
import type { Velocity } from "@/lib/types";

const LIMIT = 5;
const R = 52;
const C = 2 * Math.PI * R;

/** 5/24 at a glance. The arc springs to its new value from wherever it currently is. */
export function VelocityGauge({ v }: { v: Velocity | undefined }) {
  const count = v?.count_24m ?? 0;
  const progress = useMotionValue(0);
  const dash = useTransform(progress, (p) => `${Math.min(p, 1) * C} ${C}`);
  useEffect(() => {
    const controls = animate(progress, count / LIMIT, spring.nav);
    return () => controls.stop();
  }, [count, progress]);

  const over = count >= LIMIT;
  const color = over ? "var(--bad)" : count === LIMIT - 1 ? "var(--warn)" : "var(--ok)";
  return (
    <div className="flex items-center gap-6">
      <svg width="128" height="128" viewBox="0 0 128 128" className="shrink-0 -rotate-90" aria-hidden>
        <circle cx="64" cy="64" r={R} fill="none" stroke="var(--hairline)" strokeWidth="12" />
        <motion.circle
          cx="64"
          cy="64"
          r={R}
          fill="none"
          stroke={color}
          strokeWidth="12"
          strokeLinecap="round"
          style={{ strokeDasharray: dash }}
        />
      </svg>
      <div>
        <p className="text-[13px] font-semibold uppercase tracking-wider text-ink-2">New cards, last 24 months</p>
        <p className="headline mt-1 text-[40px] font-semibold tabular-nums">
          {v ? count : "–"}
          <span className="text-[21px] text-ink-3"> / {LIMIT}</span>
        </p>
        <p className="text-[15px] text-ink-2">
          {over
            ? "Over Chase’s 5/24 line. Chase cards are likely off the table for now."
            : `${LIMIT - count} more before Chase’s 5/24 line.`}
          {v?.next_drop_off && <> Next card ages out {shortDate(v.next_drop_off)}.</>}
        </p>
        {v && !v.complete && (
          <p className="mt-1 text-[13px] text-warn">Confirm your list below to make this count reliable.</p>
        )}
      </div>
    </div>
  );
}
