# The Advisor (v1): a read-only AgentCore agent that ranks with code and explains with Haiku

Status: accepted 2026-09-26, decided with the product owner. Builds on ADR 0001 (code ranks, the LLM
explains), 0004 (no monetization), 0005 (the Applicant Profile is the single source of truth) and
0006 (agent plane via the agentcore CLI).

## Decision

The Advisor is a Strands agent on AgentCore Runtime. The model is one setting
(`ADVISOR_MODEL_ID`). Development uses **Amazon Nova 2 Lite** (AWS's own model, covered by the
account's credits, sub-second tool calls). Claude Haiku 4.5, the first choice, is sold through
AWS Marketplace by Anthropic, where promotional credits likely don't apply; DeepSeek V3.1, the
second, stopped responding on this account on 2026-09-28 (as did Kimi K2.5), while Nova and
Qwen3 answered normally. The production model is chosen in S8 by running the same golden set
against the candidates. Because a small model paraphrases loosely, tools return the "why" as data
(rank, top earnings, the Offer's own wording, Minimum Spend and whether usual spending covers it,
a ready-made `card:` link) so the model quotes rather than recalls. v1 ("S6a") is **read-only**: it reads the user's Applicant
Profile and Wallet, ranks Card Products with deterministic code, and explains the result. Writing
(adding a Held Card, updating the Profile) comes in S6b behind AgentCore Gateway with Cedar
policies and explicit user confirmation.

### Identity and tools

- The Runtime uses `CUSTOM_JWT` and accepts only the site's Cognito web client. The user's id is
  the verified token's `sub`; nothing the model or the request body says can change it.
- Every tool calls the existing HTTP API **with the user's own access token**, so the agent has
  exactly the user's permissions: no DynamoDB access of its own, no way to read another user's
  data even under prompt injection.
- Tools: `get_my_profile`, `get_my_wallet` (with the 5/24 count), `rank_cards`,
  `check_eligibility`, `get_card_details`. All are deterministic; the model never supplies a
  fact about a card.

### Ranking (`GET /me/recommendations`, also used by non-chat pages)

```
First-year Value = Offer value (only if the Offer Verdict allows it) + 12 months of rewards − first-year fee
Ongoing Value    = 12 months of rewards − annual fee
rewards          = Σ over categories: monthly spend × 12 × rate × Point Valuation, with caps applied
```

- **Point Valuation is Conservative**, from a reviewed table with sources per currency
  (`catalog/seed/reward_currencies.yaml`): the value a bank program guarantees as cash or a
  statement credit; for airline and hotel programs, which mostly have no fixed cash value, a
  floor set below published typical redemption values. The Advisor may add what a transfer
  *could* be worth, clearly labelled, but never ranks by it.
- **"Up to" Offers** ("as high as 80,000 miles") count at the published ceiling, the same number
  the catalog headlines (ADR 0002), and are always flagged: the Advisor says "up to" and that
  many applicants are offered less. Rejected: a flat discount (no basis for the factor) and not
  counting them (would bury every Amex card).
- **Credits** (e.g. a monthly dining credit) are excluded by default. The Advisor lists them and
  asks which the user would really use; only confirmed ones are passed back to `rank_cards`.
- **Conversation what-ifs**: the saved Spending Profile is the long-term record; numbers or goals
  the user states in conversation ("say I spend $800 on dining") are passed as a `scenario` that
  overrides only what it mentions, for that one ranking, and is never stored (v1 is read-only;
  the Advisor offers a link to save them in the Profile). A first chat with no saved profile can
  still be ranked this way. The response echoes the spending it used, so answers can be traced.
- **Order follows the user's goal**: "earn Offers" ranks by First-year Value, "long-term rewards"
  by Ongoing Value; both values are always shown.
- Ineligible (application) cards are not ranked; the Advisor explains why and when to reapply.
  A card whose Offer is Ineligible is ranked without the Offer. A Minimum Spend above the user's
  usual spend is ranked but flagged with the gap. Undetermined cards are ranked with a note of
  which facts are missing.
- Issuer reward categories ("U.S. supermarkets") are mapped per card to a fixed set of spending
  categories by a reviewed table (`catalog/seed/earning_categories.yaml`); text alone isn't
  enough ("Hotels & Resorts" on a Hilton card means Hilton only). Rates that need something the
  Spending Profile can't show (an issuer travel portal, one brand, a chosen or rotating
  category, a deposit relationship, a business category, a time window) count only when the
  user says they apply, like credits; the Advisor mentions them either way.

### Spending Profile

The Applicant Profile gains monthly spend per category (dining, groceries, flights, hotels, other
travel, gas/EV, transit, streaming, online shopping, drugstores, everything else), goals (earn
Offers, long-term rewards, travel, cash back, build credit), an annual-fee ceiling, whether
business cards are wanted, and a **source** field (`manual` now). A later import of card
transactions will fill the same fields with `source: statements`; ranking, the Advisor and the
pages do not change.

### Eligibility Rules

Amex's product-family ladder is added as an Offer Rule: within a family an applicant can earn
each Offer once going up the ladder, but not a lower tier after holding a higher one (e.g. no Gold
Offer after Platinum). Each ladder is encoded only from Amex's official offer terms, with the
source recorded, never from memory (`catalog/seed/amex_offer_terms.yaml`; the terms pages are
closed to crawlers by robots.txt, so a person copied them from a browser). Cards named in the
terms but absent from the catalog (e.g. the Schwab Platinum) aren't supported yet: a Wallet
can't hold them, so their holders may be told an Offer is available when it isn't.

### Conversation

- Replies follow the user's language; short; asks one or two questions when the Profile lacks what
  ranking needs; at most three cards, each with reasons and both values; the first recommendation
  in a conversation carries a "not financial advice" note. Scope is Card Products, eligibility and
  US credit basics; unrelated requests are declined politely.
- A conversation resumes on the same device; "New conversation" starts another. AgentCore Memory
  keeps only **user preferences and conversation summaries** across conversations (ADR 0005);
  facts like score or tax id always come from the Profile. Deleting an account also deletes the
  user's Memory records.
- What is stored, and for how long (decided 2026-09-29):
  - The user's access token is never stored. It lives only in the request, and the agent drops
    it when the reply ends.
  - Raw conversation events (messages, and tool results that may include Profile ranges) stay in
    AgentCore Memory for **7 days** (`eventExpiryDuration`, counted per event from when it was
    written, whether or not it is read again).
  - The preferences and summaries extracted from them stay until the account is deleted.
  - Our table stores only the daily message count (`QUOTA#<day>`, removed by TTL), never message
    text.
  - The web shows one conversation per device, with no list of past conversations in v1. The
    daily quota is shared by all of a user's conversations.
- Links: the model may only write `card:<id>` links; the site renders them as the card's official
  Issuer URL from the Catalog Snapshot and strips every other URL, so the model can't produce a
  wrong or malicious link. No affiliate links (ADR 0004).
- Recommended cards render as tiles with an Apply button; the chat is a floating button on every
  page plus a full `/advisor` page.

### Cost control

Each user gets **10 messages per day**, reset at midnight US Eastern, enforced by the API
(`POST /me/chat/turn`, an atomic DynamoDB counter) before the model is called; the UI shows what
is left. Estimated cost is about $0.02 per turn with Haiku 4.5. Deploying the Runtime needs the
owner's approval with a cost estimate.

## Considered options

- **Let the model pick the cards**: rejected (ADR 0001): not reproducible, not testable, and prone
  to recommending the wrong card.
- **Store spending only in Memory**: rejected: fuzzy text can't be ranked precisely, and it would
  be a second copy of Profile data (ADR 0005).
- **Travel (transfer) valuations for ranking**: rejected as the default; they overstate value for
  people who don't transfer points.
- **Counting credits at face value**: rejected; most people don't use them all, which would push
  high-fee cards to the top.
- **Agent reads DynamoDB directly**: rejected: it would need its own data permissions; calling the
  API with the user's token keeps the agent's permissions equal to the user's.
- **Gateway + Cedar in v1**: deferred to S6b, where it governs write actions; v1's tools only read
  the caller's own data.

## Consequences

- Catalog coverage stays at 53 open cards for v1; P1 cards, Barclays and more business cards come
  later.
- New reviewed data: the category mapping table, the point valuation table and the Amex ladders.
- The same ranking serves the chat and the web pages, so answers and pages always agree.
