"use client";

import { motion } from "motion/react";
import { useId } from "react";

import { press, spring } from "@/lib/motion";

/** iOS segmented control: the selection pill glides between segments on a no-overshoot spring
 *  and can be redirected mid-flight (layout animations start from the live position). */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  const id = useId();
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-full bg-black/[0.05] p-0.5 dark:bg-white/10">
      {options.map((o) => {
        const selected = o.value === value;
        return (
          <motion.button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={selected}
            whileTap={press}
            transition={spring.micro}
            onClick={() => onChange(o.value)}
            className={`relative rounded-full px-3.5 py-1.5 text-[13px] font-medium ${selected ? "text-ink" : "text-ink-2"}`}
          >
            {selected && (
              <motion.span
                layoutId={`seg-${id}`}
                transition={spring.nav}
                className="absolute inset-0 rounded-full bg-surface shadow-[0_1px_3px_rgba(0,0,0,0.12)]"
              />
            )}
            <span className="relative">{o.label}</span>
          </motion.button>
        );
      })}
    </div>
  );
}
