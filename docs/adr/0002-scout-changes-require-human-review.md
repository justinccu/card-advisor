# Scout findings enter the catalog only through human review

Every Scout finding becomes a Proposed Change (source URL, extracted content, confidence) that a human approves before publication. Auto-publishing was rejected because sources include forums and blogs, and a wrong Offer can cause a user to apply for the wrong card. Auto-approval may later be allowed for structured diffs of official Issuer pages above a measured-accuracy threshold.

## Catalog v1 (2026-09-25)

v1 was not reviewed card-by-card in `scout review`. Instead, the DeepSeek V3.1 extraction was checked field-by-field against issuer pages (506 fields: 493 confirmed, 8 not quoted on the page, 5 mismatched) and promoted with `scout publish --from-preview --verification`. The 5 mismatched credits were dropped rather than corrected; the 8 unquoted fields (all card network) were kept. Later versions return to human review, using cross-model agreement (DeepSeek vs Kimi) to decide which fields need a person's attention.

## Overrides and offer variants (2026-09-25)

- **Human corrections are durable.** `catalog/seed/overrides.yaml` holds per-field corrections with a reason and verification date; they are applied last whenever a catalog file is written, so a later model run cannot silently reintroduce a value a person already fixed (first case: Hilton Surpass, whose HTML carries a hidden "$0 first year" the rendered page never shows). A note is printed when an override now matches the extraction, so stale overrides can be removed.
- **Model input is rendered visible text, never raw HTML (an architecture rule, not a prompt rule).** Every page is fetched as HTML and rendered; extraction refuses any cached page that was not rendered. If rendering fails, the page is recorded as `render_failed`; the HTML is never promoted to model input.
- **Wait for the offer, not a fixed delay.** After DOMContentLoaded the page's visible text is polled until offer text (offer wording next to a number, e.g. "As High As 80,000 Bonus Miles", "$250 Statement Credit") is present *and* the text has held steady for a second, up to 20 s. Stability matters: issuers server-render offer-looking text that personalization then replaces. If no offer text appears, the page is honestly recorded as `offer_text_seen: false` (hidden or no offer). Polling reads the DOM from Python because some issuer pages disable `eval`, which `wait_for_function` relies on.
- **Raw-HTML-only numbers are quarantined.** Fee/offer numbers present in the HTML but not on the rendered page mark the card `varies_by_visitor` and are listed in `quarantine`; they can never become the offer or any field value.
- The crawler identity stays honest (own User-Agent, fresh context, no cookie seeding or simulated browsing), and blocks are recorded rather than worked around.
- **The headline offer is the largest publicly shown number, not the highest expected value.** Across a card's main page and public campaign pages, only disclosed amounts in the same unit compete. A ceiling ("as high as 100,000", `amount_is_up_to`) can beat a fixed 90,000 even though typical applicants may get less, so the flag travels with the chosen offer and the site renders it as "Up to". Every variant is kept in `offer_variants` with its source and fetch time.

## Catalog v3: gated updates from a re-extraction run (2026-09-26)

- **Quotes must hold the number.** A quote that is on the page but lacks the extracted number (value 80,000 quoting "Earn 75,000 points") is `value_not_in_quote` and flagged like an unverified quote. Applies to fees, offer amount, minimum spend and the offer's statement credit. `approximate` (the quote's words in order with a few elided) counts as grounded.
- **`scout publish --from-latest --update-from-run <run>`** replaces a published card with its re-extraction only if every fee and offer field is grounded; otherwise the published card is kept and the reason printed. Flagged perks or earning rates don't block the update but are listed. The replaced card's `verified_at` is its fetch time (an automated quote check, not a person).
- **Ceilings count as public.** Amex shows "as high as 100,000 ... find out your offer": the exact amount is personal, but the ceiling is public, so it competes for the headline and is shown as "Up to".
- **Overrides can add list items** (`op: add` for credits/earning rates), matched by description rather than list position; `match:` (regex) supersedes an extracted item the model worded differently.

## Catalog v4: every open card extracted from rendered text (2026-09-26)

v1 had been extracted before the rendered-only rule: 20 of 53 pages went to the model as raw-HTML text. All 45 remaining open cards were re-extracted from fresh renders and merged with the same gate (1 card kept its v3 values). Deterministic normalizations at publish time handle recurring model contradictions: a quoted fixed amount is disclosed; a cash amount counted both as `amount` and `statement_credit_usd` is counted once; an offer with no amount, credit or spend requirement is no offer. Rewards-calculator defaults ("Monthly card spend $2,200") are excluded from HTML/render divergence, since they are neither fee nor offer.
