"use client";

import { motion } from "motion/react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { capLabel, fee, money, offerHeadline, offerTerms, rateLabel, sentenceCase } from "@/lib/format";
import { spring } from "@/lib/motion";
import type { CatalogCard } from "@/lib/types";

import { CardArt } from "./CardArt";
import { useCompare } from "./Providers";

export function CompareView({ cards }: { cards: CatalogCard[] }) {
  const params = useSearchParams();
  const { ids: selected } = useCompare();
  const fromUrl = (params.get("ids") ?? "").split(",").filter(Boolean);
  const ids = (fromUrl.length ? fromUrl : selected).slice(0, 3);
  const chosen = ids.map((id) => cards.find((c) => c.id === id)).filter(Boolean) as CatalogCard[];

  if (chosen.length === 0) {
    return (
      <div className="py-24 text-center">
        <p className="text-[21px] font-semibold">Nothing to compare yet.</p>
        <p className="mt-2 text-[17px] text-ink-2">Pick up to three cards from the catalog.</p>
        <Link href="/cards/" className="mt-6 inline-block text-[17px] text-link hover:underline">
          Browse cards ›
        </Link>
      </div>
    );
  }

  const lowestFee = Math.min(...chosen.map((c) => c.annual_fee_usd ?? Infinity));
  const rows: { label: string; render: (c: CatalogCard) => React.ReactNode }[] = [
    {
      label: "Annual fee",
      render: (c) => (
        <span className={c.annual_fee_usd === lowestFee && chosen.length > 1 ? "font-semibold text-ok" : ""}>
          {fee(c)}
        </span>
      ),
    },
    {
      label: "Welcome offer",
      render: (c) => (
        <>
          <span className="font-semibold">{offerHeadline(c.offer)}</span>
          {offerTerms(c.offer) && <span className="block text-ink-2">{offerTerms(c.offer)}</span>}
        </>
      ),
    },
    {
      label: "Rewards",
      render: (c) => (
        <ul className="space-y-1">
          {[...c.earning_rates]
            .sort((a, b) => b.rate - a.rate)
            .slice(0, 5)
            .map((r, i) => (
              <li key={i}>
                <span className="font-semibold tabular-nums">{rateLabel(r)}</span> {sentenceCase(r.category)}
                {capLabel(r) && <span className="block text-[12px] text-ink-2">{capLabel(r)}</span>}
              </li>
            ))}
        </ul>
      ),
    },
    {
      label: "Credits",
      render: (c) =>
        c.credits.length ? (
          <ul className="space-y-1">
            {c.credits.slice(0, 5).map((cr, i) => (
              <li key={i}>
                {cr.amount_usd != null ? `${money(cr.amount_usd)} ` : ""}
                {cr.description}
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-ink-2">None listed</span>
        ),
    },
    {
      label: "Foreign transaction fee",
      render: (c) =>
        c.foreign_transaction_fee_pct == null ? "Not stated" : c.foreign_transaction_fee_pct === 0 ? "None" : `${c.foreign_transaction_fee_pct}%`,
    },
    { label: "Applies with", render: (c) => c.accepted_tax_ids.join(" or ") },
  ];

  return (
    <div className="no-scrollbar -mx-4 overflow-x-auto px-4">
      <div
        className="grid min-w-[640px] gap-x-6"
        style={{ gridTemplateColumns: `repeat(${chosen.length}, minmax(200px, 1fr))` }}
      >
        {chosen.map((c, i) => (
          <motion.div
            key={c.id}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ ...spring.nav, delay: i * 0.05 }}
            className="text-center"
          >
            <CardArt issuerId={c.issuer_id} name={c.name} interactive className="mx-auto w-full max-w-[240px]" />
            <h2 className="mt-5 text-[21px] font-semibold tracking-tight">{c.name}</h2>
            <Link href={`/cards/${c.id}/`} className="text-[13px] text-link hover:underline">
              Details ›
            </Link>
          </motion.div>
        ))}
        {rows.map((row) =>
          chosen.map((c, i) => (
            <div key={`${row.label}-${c.id}`} className="border-t border-hairline py-4 text-[14px] leading-snug">
              <p className={`mb-1 text-[12px] font-semibold uppercase tracking-wider text-ink-3 ${i ? "invisible" : ""}`}>
                {row.label}
              </p>
              {row.render(c)}
            </div>
          )),
        )}
      </div>
    </div>
  );
}
