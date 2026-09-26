"use client";

import { Check, Plus } from "lucide-react";
import { motion } from "motion/react";

import { fee, offerHeadline, offerTerms, rateLabel, topRate } from "@/lib/format";
import { press, spring } from "@/lib/motion";
import type { CatalogCard } from "@/lib/types";

import { CardArt } from "./CardArt";
import { useCompare } from "./Providers";

export function CardTile({ card, onOpen }: { card: CatalogCard; onOpen: () => void }) {
  const { ids, toggle } = useCompare();
  const comparing = ids.includes(card.id);
  const full = ids.length >= 3 && !comparing;
  const best = topRate(card);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={spring.nav}
      className="group relative flex flex-col rounded-[24px] bg-surface p-5 shadow-[var(--shadow)] ring-1 ring-hairline"
    >
      <motion.button
        type="button"
        onClick={onOpen}
        whileTap={press}
        transition={spring.micro}
        className="text-left"
        aria-label={`Open ${card.name}`}
      >
        <CardArt cardId={card.id} issuerId={card.issuer_id} name={card.name} className="mx-auto w-full max-w-[260px]" />
        <h3 className="mt-5 text-[17px] font-semibold leading-snug">{card.name}</h3>
        <p className="mt-0.5 text-[13px] text-ink-2">{fee(card)}</p>
        <p className="mt-3 text-[15px] font-medium">{offerHeadline(card.offer)}</p>
        <p className="text-[13px] text-ink-2">{offerTerms(card.offer) ?? " "}</p>
        {best && (
          <p className="mt-2 text-[13px] text-ink-2">
            Up to <span className="font-semibold text-ink">{rateLabel(best)}</span> on {best.category}
          </p>
        )}
      </motion.button>
      <motion.button
        type="button"
        whileTap={press}
        transition={spring.micro}
        disabled={full}
        onClick={() => toggle(card.id)}
        aria-pressed={comparing}
        className={`mt-4 inline-flex items-center justify-center gap-1.5 self-start rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors disabled:opacity-40 ${comparing ? "bg-action text-white" : "bg-black/[0.05] text-ink dark:bg-white/10"}`}
      >
        {comparing ? <Check size={14} /> : <Plus size={14} />}
        {comparing ? "Comparing" : "Compare"}
      </motion.button>
    </motion.div>
  );
}
