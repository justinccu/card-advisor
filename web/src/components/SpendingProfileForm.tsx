"use client";

import { motion } from "motion/react";
import { useState } from "react";

import { press, spring } from "@/lib/motion";
import type { Goal, SpendCategory, SpendingProfile } from "@/lib/types";

const CATEGORIES: { key: SpendCategory; label: string; hint?: string }[] = [
  { key: "dining", label: "Dining", hint: "restaurants, takeout, delivery" },
  { key: "groceries", label: "Groceries" },
  { key: "flights", label: "Flights" },
  { key: "hotels", label: "Hotels" },
  { key: "other_travel", label: "Other travel", hint: "car rentals, cruises, tours" },
  { key: "gas_ev", label: "Gas & EV charging" },
  { key: "transit", label: "Transit & commuting" },
  { key: "streaming", label: "Streaming" },
  { key: "online_shopping", label: "Online shopping" },
  { key: "drugstores", label: "Drugstores" },
  { key: "everything_else", label: "Everything else" },
];

const GOALS: { value: Goal; label: string }[] = [
  { value: "earn_offers", label: "Earn welcome offers" },
  { value: "long_term", label: "Long-term rewards" },
  { value: "travel", label: "Travel" },
  { value: "cash_back", label: "Cash back" },
  { value: "build_credit", label: "Build credit (first card)" },
];

const FEE_LIMITS: { value: number | null; label: string }[] = [
  { value: 0, label: "No annual fee" },
  { value: 100, label: "Up to $100" },
  { value: 300, label: "Up to $300" },
  { value: null, label: "Any fee" },
];

export const EMPTY_SPENDING: SpendingProfile = {
  monthly_usd: {},
  goals: [],
  max_annual_fee_usd: null,
  wants_business: false,
  source: "manual",
};

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

/**
 * The Spending Profile (ADR 0009): monthly spend per category and what the user wants. Amounts
 * save when a field loses focus; choices save on tap. Rough numbers are fine; ranking only needs
 * the shape of the spending.
 */
export function SpendingProfileForm({
  value,
  onChange,
}: {
  value: SpendingProfile | null | undefined;
  onChange: (next: SpendingProfile) => void;
}) {
  const spending = value ?? EMPTY_SPENDING;
  // Text while typing, so "" and partial numbers don't fight the saved value.
  const [draft, setDraft] = useState<Partial<Record<SpendCategory, string>>>({});
  const total = Object.values(spending.monthly_usd).reduce((a, b) => a + (b ?? 0), 0);
  const save = (patch: Partial<SpendingProfile>) =>
    onChange({ ...spending, ...patch, source: "manual" });

  const commit = (key: SpendCategory) => {
    const raw = draft[key];
    if (raw === undefined) return;
    const amount = Math.max(0, Math.round(Number(raw.replace(/[^0-9.]/g, "")) || 0));
    const monthly = { ...spending.monthly_usd };
    if (amount) monthly[key] = amount;
    else delete monthly[key];
    setDraft((d) => {
      const next = { ...d };
      delete next[key];
      return next;
    });
    if ((spending.monthly_usd[key] ?? 0) !== amount) save({ monthly_usd: monthly });
  };

  const toggleGoal = (goal: Goal) =>
    save({
      goals: spending.goals.includes(goal)
        ? spending.goals.filter((g) => g !== goal)
        : [...spending.goals, goal],
    });

  return (
    <div className="space-y-8">
      <section>
        <h2 className="text-[17px] font-semibold">Monthly spending</h2>
        <p className="mb-3 text-[13px] text-ink-2">
          Rough numbers are fine. The Advisor uses them to estimate what each card would earn you.
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {CATEGORIES.map((c) => {
            const saved = spending.monthly_usd[c.key];
            const shown = draft[c.key] ?? (saved ? String(saved) : "");
            return (
              <label
                key={c.key}
                className="flex items-center justify-between gap-3 rounded-2xl border border-hairline px-4 py-2.5"
              >
                <span className="min-w-0">
                  <span className="block text-[15px]">{c.label}</span>
                  {c.hint && <span className="block truncate text-[12px] text-ink-3">{c.hint}</span>}
                </span>
                <span className="flex shrink-0 items-center gap-1 text-[15px] text-ink-2">
                  $
                  <input
                    inputMode="numeric"
                    aria-label={`${c.label} per month`}
                    value={shown}
                    placeholder="0"
                    onChange={(e) => setDraft((d) => ({ ...d, [c.key]: e.target.value }))}
                    onBlur={() => commit(c.key)}
                    onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                    className="w-20 bg-transparent text-right text-ink tabular-nums outline-none"
                  />
                  <span className="text-[12px]">/mo</span>
                </span>
              </label>
            );
          })}
        </div>
        <p className="mt-2 text-right text-[13px] text-ink-2">
          About <span className="tabular-nums text-ink">{usd.format(total)}</span> a month
        </p>
      </section>

      <section>
        <h2 className="text-[17px] font-semibold">What you want from a card</h2>
        <p className="mb-3 text-[13px] text-ink-2">Pick any that apply.</p>
        <div className="flex flex-wrap gap-2">
          {GOALS.map((g) => (
            <Pill key={g.value} on={spending.goals.includes(g.value)} onClick={() => toggleGoal(g.value)}>
              {g.label}
            </Pill>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-[17px] font-semibold">Annual fee you&apos;d pay</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {FEE_LIMITS.map((f) => (
            <Pill
              key={f.label}
              on={spending.max_annual_fee_usd === f.value}
              onClick={() => save({ max_annual_fee_usd: f.value })}
            >
              {f.label}
            </Pill>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-[17px] font-semibold">Business cards</h2>
        <p className="mb-3 text-[13px] text-ink-2">Include cards for a business or side business.</p>
        <div className="flex gap-2">
          <Pill on={spending.wants_business} onClick={() => save({ wants_business: true })}>
            Include
          </Pill>
          <Pill on={!spending.wants_business} onClick={() => save({ wants_business: false })}>
            Personal only
          </Pill>
        </div>
      </section>
    </div>
  );
}

function Pill({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <motion.button
      type="button"
      whileTap={press}
      transition={spring.micro}
      onClick={onClick}
      aria-pressed={on}
      className={`rounded-full px-4 py-2 text-[14px] ring-1 transition-colors ${on ? "bg-ink text-canvas ring-ink" : "ring-hairline"}`}
    >
      {children}
    </motion.button>
  );
}
