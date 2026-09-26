import { BadgeCheck, ExternalLink } from "lucide-react";

import {
  capLabel,
  creditLabel,
  creditWindow,
  fee,
  offerCreditLabel,
  offerEnds,
  offerHeadline,
  offerTerms,
  rateLabel,
  sentenceCase,
} from "@/lib/format";
import { issuerName } from "@/lib/issuers";
import type { CatalogCard } from "@/lib/types";

import { CardArt } from "./CardArt";

const longDate = (iso: string) =>
  new Date(iso.length === 10 ? `${iso}T00:00:00` : iso).toLocaleDateString("en-US", {
    dateStyle: "medium",
  });

export function CardDetail({ card, children }: { card: CatalogCard; children?: React.ReactNode }) {
  const terms = offerTerms(card.offer);
  const offerCredit = offerCreditLabel(card.offer);
  const ends = offerEnds(card.offer);
  // Snapshots published before these fields existed simply lack them.
  const manual = card.manually_verified ?? {};
  const feeCheckedByHand = manual.annual_fee_usd ?? manual.first_year_annual_fee_usd;
  const chosenSource = (card.offer_variants ?? []).find(
    (v) => v.offer && card.offer && v.offer.amount === card.offer.amount && v.offer.unit === card.offer.unit,
  );
  return (
    <article className="space-y-8">
      <header className="grid items-center gap-6 sm:grid-cols-[220px_1fr]">
        <CardArt cardId={card.id} issuerId={card.issuer_id} name={card.name} interactive className="mx-auto w-[220px]" />
        <div className="text-center sm:text-left">
          <p className="text-[13px] font-medium text-ink-2">{issuerName(card.issuer_id)}</p>
          <h2 className="headline mt-1 text-[28px] font-semibold">{card.name}</h2>
          <p className="mt-2 text-[15px] text-ink-2">{fee(card)}</p>
          {feeCheckedByHand && (
            <p className="mt-1 inline-flex items-center gap-1 text-[12px] text-ok">
              <BadgeCheck size={13} aria-hidden /> Fee verified by hand · {longDate(feeCheckedByHand)}
            </p>
          )}
        </div>
      </header>

      <section className="rounded-2xl bg-tile p-5">
        <h3 className="text-[12px] font-semibold uppercase tracking-wider text-ink-2">Welcome offer</h3>
        <p className="headline mt-1 text-[24px] font-semibold">{offerHeadline(card.offer)}</p>
        {offerCredit && <p className="headline text-[17px] font-semibold">{offerCredit}</p>}
        {terms && <p className="text-[15px] text-ink-2">{terms}</p>}
        {ends && <p className="mt-1 text-[13px] font-medium text-warn">{ends}</p>}
        {card.offer && !card.offer.amount_disclosed && !card.offer.amount_is_up_to && (
          <p className="mt-2 text-[13px] text-ink-2">
            The issuer shows a personalized amount during the application; offers vary by applicant.
          </p>
        )}
        {card.offer?.amount_is_up_to && (
          <p className="mt-2 text-[13px] text-ink-2">
            This is the most the issuer advertises. Many applicants are offered less; you&apos;ll see
            your amount when you apply.
          </p>
        )}
        {card.varies_by_visitor && (
          <p className="mt-2 text-[13px] text-warn">
            This issuer shows different terms to different visitors. We list what a first-time
            visitor sees
            {chosenSource?.fetched_at ? ` (checked ${longDate(chosenSource.fetched_at)})` : ""}; confirm
            the fee and offer on the application page.
            {chosenSource && chosenSource.profile === "campaign" && (
              <>
                {" "}The amount above is the largest public offer we found, on{" "}
                <a href={chosenSource.source_url} target="_blank" rel="noopener noreferrer" className="underline">
                  a campaign page
                </a>
                .
              </>
            )}
          </p>
        )}
      </section>

      {card.earning_rates.length > 0 && (
        <section>
          <h3 className="text-[17px] font-semibold">Rewards</h3>
          <ul className="mt-3 divide-y divide-hairline">
            {[...card.earning_rates]
              .sort((a, b) => b.rate - a.rate)
              .map((r, i) => (
                <li key={i} className="flex items-baseline gap-4 py-2.5">
                  <span className="w-12 shrink-0 text-[17px] font-semibold tabular-nums">{rateLabel(r)}</span>
                  <span className="text-[15px]">
                    {sentenceCase(r.category)}
                    {capLabel(r) && <span className="block text-[13px] text-ink-2">{capLabel(r)}</span>}
                  </span>
                </li>
              ))}
          </ul>
        </section>
      )}

      {card.credits.length > 0 && (
        <section>
          <h3 className="text-[17px] font-semibold">Credits &amp; perks</h3>
          <ul className="mt-3 space-y-3">
            {card.credits.map((c, i) => {
              const window = creditWindow(c);
              const byHand = manual[`credits:${c.description}`];
              return (
                <li key={i} className="text-[15px]">
                  <div className="flex justify-between gap-4">
                    <span>{c.description}</span>
                    <span className="shrink-0 text-ink-2">{creditLabel(c)}</span>
                  </div>
                  {(c.conditions || window || byHand) && (
                    <p className="mt-0.5 text-[13px] text-ink-2">
                      {[c.conditions && sentenceCase(c.conditions), window].filter(Boolean).join(" · ")}
                      {byHand && (
                        <span className="ml-1 inline-flex items-center gap-1 text-ok">
                          <BadgeCheck size={12} aria-hidden /> verified by hand
                        </span>
                      )}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <section className="grid grid-cols-2 gap-3 text-[13px]">
        <Fact label="Foreign transaction fee" value={card.foreign_transaction_fee_pct == null ? "Not stated" : card.foreign_transaction_fee_pct === 0 ? "None" : `${card.foreign_transaction_fee_pct}%`} />
        <Fact label="Applies with" value={card.accepted_tax_ids.join(" or ")} />
        <Fact label="Type" value={`${card.is_business ? "Business" : "Personal"} ${card.is_charge_card ? "charge card" : "credit card"}`} />
        <Fact label="Network" value={card.network ?? "Not stated"} />
      </section>

      {children}

      <a
        href={card.url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-[15px] text-link hover:underline"
      >
        Terms on {issuerName(card.issuer_id)}&apos;s site <ExternalLink size={14} aria-hidden />
      </a>
      {card.verified_at && (
        <p className="text-[12px] text-ink-3">Details checked against the issuer&apos;s page on {longDate(card.verified_at)}.</p>
      )}
    </article>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-hairline p-3">
      <p className="text-ink-2">{label}</p>
      <p className="mt-0.5 font-medium">{value}</p>
    </div>
  );
}
