// Mirrors card_rules.catalog and the API models. Names follow CONTEXT.md.

export type TaxId = "SSN" | "ITIN" | "NONE";

export interface Offer {
  amount_disclosed: boolean;
  amount: number | null;
  /** "as high as" / "up to": amount is a ceiling, not what every applicant gets */
  amount_is_up_to: boolean;
  unit: "points" | "miles" | "usd" | "gift_card_usd" | "cashback_match" | "free_nights";
  min_spend_usd: number | null;
  spend_window_months: number | null;
  /** Dollar half of a two-part offer ("a $250 statement credit and 80,000 miles") */
  statement_credit_usd: number | null;
  /** ISO date the public offer ends */
  ends_on: string | null;
}

export interface EarningRate {
  category: string;
  rate: number;
  unit: "x_points" | "x_miles" | "percent_cash_back";
  cap_usd: number | null;
  cap_period: string | null;
}

export interface Credit {
  description: string;
  amount_usd: number | null;
  period: string;
  /** Percentage perks ("25% back on inflight purchases") have no dollar amount */
  percent: number | null;
  valid_from: string | null;
  valid_until: string | null;
  conditions: string | null;
}

/** A bank's display name and the other names people search it by ("Amex"). */
export interface Issuer {
  name: string;
  aliases: string[];
}

export interface CatalogCard {
  id: string;
  /** other names people search this card by ("CSP") */
  aliases?: string[];
  issuer_id: string;
  name: string;
  family: string | null;
  is_business: boolean;
  is_charge_card: boolean;
  accepted_tax_ids: TaxId[];
  url: string;
  availability: "open" | "closed_to_new_applicants";
  closed_on: string | null;
  tags: string[];
  annual_fee_usd: number | null;
  first_year_annual_fee_usd: number | null;
  foreign_transaction_fee_pct: number | null;
  network: string | null;
  offer: Offer | null;
  earning_rates: EarningRate[];
  credits: Credit[];
  notes: string;
  verified_at: string | null;
  offer_variants: OfferVariant[];
  /** How `offer` was chosen: the largest publicly shown number, not the highest expected value */
  offer_basis: "max_public_number";
  varies_by_visitor: boolean;
  /** field -> ISO date a person verified it (catalog/seed/overrides.yaml) */
  manually_verified: Record<string, string>;
}

export interface OfferVariant {
  source_url: string;
  profile: "fresh" | "campaign" | "http";
  offer: Offer | null;
  fetched_at: string | null;
}

export interface CatalogSnapshot {
  /** "MAJOR.MINOR"; the local preview is "0.0" */
  version: string;
  market: string;
  generated_at: string;
  preview: boolean;
  cards: CatalogCard[];
  /** by issuer_id; absent in snapshots before v1.6 */
  issuers?: Record<string, Issuer>;
}

export type Status = "Eligible" | "Ineligible" | "Undetermined";

export interface Reason {
  rule_id: string;
  status: Status;
  message: string;
  confidence: "official" | "community";
  source_url: string | null;
  retry_after: string | null;
}

export interface Verdict {
  status: Status;
  reasons: Reason[];
  warnings: Reason[];
}

export interface Evaluation {
  name: string;
  card_product_id: string;
  as_of: string;
  application: Verdict;
  offer: Verdict;
}

/** /me/eligibility: verdicts plus the catalog version they were computed from */
export interface EligibilityResult {
  catalog_version: string;
  evaluations: Evaluation[];
}

export interface HeldCardIn {
  card_product_id?: string | null;
  issuer_id?: string | null;
  name?: string | null;
  opened_on: string;
  closed_on?: string | null;
  is_authorized_user?: boolean;
  is_business?: boolean;
  bonus_received_on?: string | null;
}

export interface HeldCard extends HeldCardIn {
  id: string;
}

/** Corrections to a held card; only the fields sent change (`closed_on: null` reopens it). */
export type HeldCardPatch = Partial<Pick<HeldCardIn, "opened_on" | "closed_on" | "is_authorized_user">>;

export interface WalletAttestation {
  complete_since: string | null;
  includes_all_open_cards: boolean;
  full_history_issuers: string[];
}

export interface Wallet {
  cards: HeldCard[];
  attestation: WalletAttestation;
}

export interface Velocity {
  count_24m: number;
  next_drop_off: string | null;
  complete: boolean;
}

export type SpendCategory =
  | "dining"
  | "groceries"
  | "flights"
  | "hotels"
  | "other_travel"
  | "gas_ev"
  | "transit"
  | "streaming"
  | "online_shopping"
  | "drugstores"
  | "everything_else";

export type Goal = "earn_offers" | "long_term" | "travel" | "cash_back" | "build_credit";

/** What ranking uses (ADR 0009). `source` is manual for now; imported statements later. */
export interface SpendingProfile {
  monthly_usd: Partial<Record<SpendCategory, number>>;
  goals: Goal[];
  max_annual_fee_usd: number | null;
  wants_business: boolean;
  source: "manual" | "statements";
}

export interface ApplicantProfile {
  tax_id: TaxId | null;
  score_band: string | null;
  income_band: string | null;
  credit_history: string | null;
  spending?: SpendingProfile | null;
}

/** Advisor messages left today (ADR 0009: 30 per user per day, reset at midnight US Eastern). */
export interface ChatQuota {
  limit: number;
  used: number;
  remaining: number;
  resets_at: string;
}

export type FeedbackReason = "wrong_info" | "not_what_i_asked" | "missing_info" | "other";

/** 👍 / 👎 on one Advisor answer (ADR 0009); rating keeps that exchange 90 days. */
export interface TurnFeedback {
  rating: "up" | "down";
  reason?: FeedbackReason;
  comment?: string;
}
