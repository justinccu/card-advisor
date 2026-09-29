import type { CatalogCard, Credit, EarningRate, Offer } from "./types";

// Whole dollars stay whole ($95); cents show when the issuer states them ($12.95).
const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});
const num = new Intl.NumberFormat("en-US");

export const money = (n: number | null | undefined) => (n == null ? "—" : usd.format(n));

export function fee(card: Pick<CatalogCard, "annual_fee_usd" | "first_year_annual_fee_usd">): string {
  if (card.annual_fee_usd == null) return "Fee not listed";
  if (card.annual_fee_usd === 0) return "No annual fee";
  if (card.first_year_annual_fee_usd === 0) return `${money(card.annual_fee_usd)} · $0 first year`;
  return `${money(card.annual_fee_usd)} annual fee`;
}

const UNIT: Record<Offer["unit"], string> = {
  points: "points",
  miles: "miles",
  usd: "cash back",
  gift_card_usd: "gift card",
  cashback_match: "Cashback Match",
  free_nights: "free nights",
};

/** The number a visitor can see: a fixed amount, or a ceiling ("as high as") even when the exact
 *  offer is revealed only on applying. */
export function publicAmount(offer: Offer | null): number | null {
  if (!offer || offer.amount == null) return null;
  return offer.amount_disclosed || offer.amount_is_up_to ? offer.amount : null;
}

export function offerHeadline(offer: Offer | null): string {
  if (!offer) return "No welcome offer";
  if (offer.unit === "cashback_match") return "Cashback Match, year one";
  const amount = publicAmount(offer);
  if (amount == null) return "Offer shown when you apply";
  const upTo = offer.amount_is_up_to ? "Up to " : "";
  if (offer.unit === "usd" || offer.unit === "gift_card_usd")
    return `${upTo}${money(amount)} ${UNIT[offer.unit]}`;
  return `${upTo}${num.format(amount)} ${UNIT[offer.unit]}`;
}

export function offerTerms(offer: Offer | null): string | null {
  if (!offer?.min_spend_usd) return null;
  const window = offer.spend_window_months ? ` in ${offer.spend_window_months} months` : "";
  return `after ${money(offer.min_spend_usd)} spend${window}`;
}

/** The dollar half of a two-part offer, e.g. "+ $250 statement credit". */
export function offerCreditLabel(offer: Offer | null): string | null {
  return offer?.statement_credit_usd ? `+ ${money(offer.statement_credit_usd)} statement credit` : null;
}

export function offerEnds(offer: Offer | null): string | null {
  if (!offer?.ends_on) return null;
  return `Offer ends ${new Date(`${offer.ends_on}T00:00:00`).toLocaleDateString("en-US", { dateStyle: "medium" })}`;
}

const PERIOD: Record<string, string> = {
  month: "monthly",
  quarter: "quarterly",
  semi_annual: "twice a year",
  year: "yearly",
  calendar_year: "per calendar year",
  cardmember_year: "per cardmember year",
  four_years: "every 4 years",
  one_time: "one time",
  per_use: "each time",
};

/** "$50 · each time", "25% back · each time", "Perk · one time". */
export function creditLabel(c: Credit): string {
  const amount = c.amount_usd != null ? money(c.amount_usd) : c.percent != null ? `${c.percent}% back` : "Perk";
  return `${amount} · ${PERIOD[c.period] ?? c.period.replaceAll("_", " ")}`;
}

/** "Jun 4, 2026 – Dec 31, 2026", "Through Dec 31, 2027", or null. */
export function creditWindow(c: Credit): string | null {
  const d = (iso: string) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { dateStyle: "medium" });
  if (c.valid_from && c.valid_until) return `${d(c.valid_from)} – ${d(c.valid_until)}`;
  if (c.valid_until) return `Through ${d(c.valid_until)}`;
  if (c.valid_from) return `From ${d(c.valid_from)}`;
  return null;
}

export function rateLabel(r: EarningRate): string {
  const value = r.unit === "percent_cash_back" ? `${r.rate}%` : `${r.rate}×`;
  return value;
}

export function capLabel(r: EarningRate): string | null {
  if (!r.cap_usd) return null;
  const period = r.cap_period?.replace("_", " ") ?? "";
  return `up to ${money(r.cap_usd)}${period ? ` per ${period}` : ""}`;
}

export function topRate(card: CatalogCard): EarningRate | null {
  return card.earning_rates.reduce<EarningRate | null>(
    (best, r) => (!best || r.rate > best.rate ? r : best),
    null,
  );
}

/** Sentence case (Apple style): capitalize the first letter only, keep the issuer's own casing
 *  for acronyms and brand names (e.g. "U.S. supermarkets", "EV charging"). */
export function sentenceCase(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

/** "Apr 20, 2025" */
export function fullDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { dateStyle: "medium" });
}

export function shortDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
  });
}
