"use client";

import { X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";

import { press, spring } from "@/lib/motion";
import type { CatalogCard } from "@/lib/types";

import { CardArt } from "./CardArt";
import { useCompare } from "./Providers";

/** Floating dock that springs up once something is selected. One glass layer, over content. */
export function CompareTray({ cards }: { cards: CatalogCard[] }) {
  const { ids, toggle, clear } = useCompare();
  const chosen = ids.map((id) => cards.find((c) => c.id === id)).filter(Boolean) as CatalogCard[];

  return (
    <AnimatePresence>
      {chosen.length > 0 && (
        <motion.div
          initial={{ y: 120, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 120, opacity: 0 }}
          transition={spring.sheet}
          className="glass fixed inset-x-0 bottom-4 z-40 mx-auto flex w-[min(640px,calc(100%-24px))] items-center gap-3 rounded-[22px] p-2.5 shadow-[var(--shadow-lift)] ring-1 ring-hairline"
        >
          <ul className="flex flex-1 items-center gap-2 overflow-hidden">
            <AnimatePresence initial={false}>
              {chosen.map((c) => (
                <motion.li
                  key={c.id}
                  layout
                  initial={{ scale: 0.6, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0.6, opacity: 0 }}
                  transition={spring.micro}
                  className="relative w-16 shrink-0"
                >
                  <CardArt cardId={c.id} issuerId={c.issuer_id} name={c.name} bare />
                  <button
                    onClick={() => toggle(c.id)}
                    aria-label={`Remove ${c.name}`}
                    className="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full bg-ink text-canvas"
                  >
                    <X size={11} strokeWidth={3} />
                  </button>
                </motion.li>
              ))}
            </AnimatePresence>
            <li className="ml-1 truncate text-[13px] text-ink-2">{chosen.length} of 3</li>
          </ul>
          <button onClick={clear} className="text-[13px] text-link">
            Clear
          </button>
          <motion.div whileTap={press} transition={spring.micro}>
            <Link
              href={`/compare/?ids=${ids.join(",")}`}
              className="block rounded-full bg-action px-4 py-2 text-[14px] font-medium text-white hover:bg-action-hover"
            >
              Compare
            </Link>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
