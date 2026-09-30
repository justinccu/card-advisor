"use client";

import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { publicAmount } from "@/lib/format";
import { press, spring } from "@/lib/motion";
import { searchCards } from "@/lib/search";
import type { CatalogCard, Issuer } from "@/lib/types";

import { CardDetail } from "./CardDetail";
import { CardTile } from "./CardTile";
import { CompareTray } from "./CompareTray";
import { useSession } from "./Providers";
import { Segmented } from "./Segmented";
import { Sheet } from "./Sheet";
import { Reasons, StatusPill } from "./Verdict";

type Kind = "all" | "travel" | "cashback" | "starter" | "business";
type Sort = "offer" | "fee";

const KINDS: { value: Kind; label: string }[] = [
  { value: "all", label: "All" },
  { value: "travel", label: "Travel" },
  { value: "cashback", label: "Cash back" },
  { value: "starter", label: "Starter" },
  { value: "business", label: "Business" },
];

function matchesKind(c: CatalogCard, kind: Kind): boolean {
  if (kind === "all") return true;
  if (kind === "business") return c.is_business;
  if (kind === "starter") return c.tags.some((t) => ["starter", "student", "secured"].includes(t));
  return c.tags.includes(kind) && !c.is_business;
}

// Rough, unit-agnostic ordering for "best offer first": dollars and points both compare by
// face value / 100 so 60,000 points ≈ $600. The Recommendation engine does the real valuation.
function offerWeight(c: CatalogCard): number {
  const o = c.offer;
  const amount = publicAmount(o);
  if (!o || amount == null) return -1;
  return o.unit === "usd" || o.unit === "gift_card_usd" ? amount : amount / 100;
}

export function CatalogBrowser({ cards, issuers }: { cards: CatalogCard[]; issuers: Record<string, Issuer> }) {
  const [kind, setKind] = useState<Kind>("all");
  const [sort, setSort] = useState<Sort>("offer");
  const [noFee, setNoFee] = useState(false);
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const { shown, exact } = useMemo(() => {
    const filtered = cards
      .filter((c) => matchesKind(c, kind))
      .filter((c) => !noFee || c.annual_fee_usd === 0)
      .sort((a, b) =>
        sort === "offer"
          ? offerWeight(b) - offerWeight(a)
          : (a.annual_fee_usd ?? 9999) - (b.annual_fee_usd ?? 9999),
      );
    // Search keeps the chosen order among equally good matches (the sort is stable).
    const found = searchCards(q, filtered, issuers);
    return { shown: found.cards, exact: found.exact };
  }, [cards, issuers, kind, sort, noFee, q]);

  const open = cards.find((c) => c.id === openId) ?? null;

  return (
    <>
      <div className="sticky top-12 z-30 -mx-4 mb-8 space-y-3 bg-canvas/85 px-4 pb-4 pt-3 backdrop-blur-xl">
        <div className="flex flex-wrap items-center gap-3">
          <Segmented options={KINDS} value={kind} onChange={setKind} label="Card type" />
          <motion.button
            whileTap={press}
            transition={spring.micro}
            onClick={() => setNoFee((v) => !v)}
            aria-pressed={noFee}
            className={`rounded-full px-3.5 py-1.5 text-[13px] font-medium ring-1 transition-colors ${noFee ? "bg-ink text-canvas ring-ink" : "text-ink ring-hairline"}`}
          >
            No annual fee
          </motion.button>
        </div>
        <div className="flex items-center gap-3">
          <label className="relative flex-1">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" aria-hidden />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search cards or banks"
              aria-label="Search cards"
              className="w-full rounded-xl bg-black/[0.05] py-2 pl-9 pr-3 text-[15px] outline-none placeholder:text-ink-3 focus:bg-surface focus:ring-2 focus:ring-action dark:bg-white/10"
            />
          </label>
          <Segmented
            options={[
              { value: "offer", label: "Top offers" },
              { value: "fee", label: "Lowest fee" },
            ]}
            value={sort}
            onChange={setSort}
            label="Sort"
          />
        </div>
        <p className="text-[13px] text-ink-2" aria-live="polite">
          {!exact && shown.length > 0
            ? `No exact match for “${q.trim()}”. Closest ${shown.length === 1 ? "card" : "cards"}:`
            : `${shown.length} ${shown.length === 1 ? "card" : "cards"}`}
        </p>
      </div>

      <motion.div layout className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        <AnimatePresence mode="popLayout">
          {shown.map((c) => (
            <CardTile key={c.id} card={c} onOpen={() => setOpenId(c.id)} />
          ))}
        </AnimatePresence>
      </motion.div>
      {shown.length === 0 && (
        <p className="py-24 text-center text-[17px] text-ink-2">No cards match. Try fewer filters.</p>
      )}

      <Sheet open={!!open} onClose={() => setOpenId(null)} title={open?.name ?? "Card"}>
        {open && (
          <CardDetail card={open}>
            <EligibilityPanel cardId={open.id} />
          </CardDetail>
        )}
      </Sheet>
      <CompareTray cards={cards} />
    </>
  );
}

function EligibilityPanel({ cardId }: { cardId: string }) {
  const { uid, ready } = useSession();
  const { data, isPending, error } = useQuery({
    queryKey: ["eligibility", uid, cardId],
    queryFn: () => api.eligibility([cardId]),
    enabled: !!uid,
  });

  if (!ready) return null;
  if (!uid) {
    return (
      <section className="rounded-2xl border border-hairline p-5">
        <h3 className="text-[17px] font-semibold">Can you get this card?</h3>
        <p className="mt-1 text-[15px] text-ink-2">
          Add the cards you already have and we&apos;ll check the issuer&apos;s rules, like Chase 5/24 and
          once-per-lifetime bonuses, before you apply.
        </p>
        <Link href="/signin/" className="mt-3 inline-block text-[15px] text-link hover:underline">
          Sign in to check ›
        </Link>
      </section>
    );
  }
  if (isPending) return <div className="h-28 animate-pulse rounded-2xl bg-tile" aria-busy />;
  if (error) {
    return (
      <p className="text-[13px] text-bad">
        {error instanceof ApiError && error.status === 0 ? "API offline." : "Couldn’t check eligibility."}
      </p>
    );
  }
  const [v] = data;
  return (
    <section className="space-y-4 rounded-2xl border border-hairline p-5">
      <h3 className="text-[17px] font-semibold">For you</h3>
      <div className="space-y-3">
        <div>
          <StatusPill status={v.application.status} what="Approval" />
          <div className="mt-2">
            <Reasons verdict={v.application} />
          </div>
        </div>
        <div>
          <StatusPill status={v.offer.status} what="Welcome offer" />
          <div className="mt-2">
            <Reasons verdict={v.offer} />
          </div>
        </div>
      </div>
      <Link href="/wallet/" className="inline-block text-[13px] text-link hover:underline">
        Update your wallet ›
      </Link>
    </section>
  );
}
