# The Advisor (v1): a read-only AgentCore agent that ranks with code and explains with Haiku

Status: accepted 2026-09-26, decided with the product owner. Builds on ADR 0001 (code ranks, the LLM
explains), 0004 (no monetization), 0005 (the Applicant Profile is the single source of truth) and
0006 (agent plane via the agentcore CLI).

## Decision

The Advisor is a Strands agent on AgentCore Runtime. The model is one setting
(`ADVISOR_MODEL_ID`). Development uses **Qwen3 235B** on Bedrock (billed by AWS, so covered by
the account's credits), since 2026-09-29. Before that it used Nova 2 Lite, which followed the
tool instructions poorly (see the comparison below).

Other options:
- Claude Haiku 4.5, the first choice, is sold through AWS Marketplace by Anthropic. Its Marketplace
  agreement wasn't available on this account, and promotional credits likely don't apply.
- DeepSeek V3.1 stopped responding on this account on 2026-09-28, as did Kimi K2.5.

The production model is chosen in S8 by running the same golden set against the candidates:
Qwen3, plus Claude and Gemini through their own APIs. Those two would bring an API key to store,
a bill outside the AWS credits, and user data sent outside AWS, which the ADR must then record. Because a small model paraphrases loosely, tools return the "why" as data
(rank, top earnings, the Offer's own wording, Minimum Spend and whether usual spending covers it,
a ready-made `card:` link) so the model quotes rather than recalls.

Tool results never contain a null, and fees, offers and credits are spelled out in words. Nova 2
Lite read `first_year_fee_usd: null` as "$0 the first year" for the Amex Gold ($325 every year),
so missing facts are left out and present ones are written as sentences ("$325 a year, including
the first year (no first-year discount)"). Issuer rules are explained from `get_issuer_rules`,
which the API generates from the same rule fields the engine evaluates.

Model comparison, 2026-09-29, asking "What is Chase 5/24? Do closed cards count?":
- **Nova 2 Lite** skipped the rules tool and answered from memory, getting almost everything
  wrong (it said only Chase cards count and closed cards don't).
- **Qwen3 235B** and **Nova Pro** called the tool and answered correctly. Nova Pro also leaked
  its `<thinking>` text into the reply.

Following the tool instructions is therefore a model requirement. The S8 golden set includes
these questions.

v1 ("S6a") is **read-only**: it reads the user's Applicant
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
  `check_eligibility`, `get_card_details`, `get_issuer_rules` (`GET /rules`). All are
  deterministic; the model never supplies a fact about a card or a rule.

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
  - `DELETE /me` deletes them first (`card_api.memory`), before any other data. If a record
    won't delete, the request fails with 503 and nothing is deleted; the site then keeps the
    Cognito account so the user can retry. Raw events are deleted too, in parallel, within a
    5-second budget, and any left over expire within 7 days.
  - The API's permission is list and delete only, on this one Memory. It is granted when
    `advisor_memory_id` is set in `infra/cdk.json` after `agentcore deploy`.
  - Our table stores only the daily message count (`QUOTA#<day>`, removed by TTL), never message
    text.
  - CloudWatch logs and traces from the runtime hold timing, token counts, tool names and errors,
    but no conversation text, for 7 days. On AgentCore, ADOT records message content by default,
    and a first deploy wrote user questions into a log group kept forever. Now:
    - `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false` stops ADOT recording it.
    - `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_unredacted_attributes=` makes Strands redact
      messages, the system prompt and tool inputs/outputs; `tests/test_telemetry.py` pins this.
    - `make agent-deploy` sets 7-day retention on the log groups AgentCore creates itself.
  - The web shows one conversation per device, with no list of past conversations in v1. The
    daily quota is shared by all of a user's conversations.
- Links: the model may only write `card:<id>` links; the site renders them as the card's official
  Issuer URL from the Catalog Snapshot and strips every other URL, so the model can't produce a
  wrong or malicious link. No affiliate links (ADR 0004).
- Recommended cards render as tiles with an Apply button; the chat is a floating button on every
  page plus a full `/advisor` page.
- The browser calls the Runtime directly (as in the workshop's Lab 6, but from the Next.js site):
  `POST .../runtimes/<arn>/invocations` with the Cognito access token and a per-device session
  id header. The URL is a build setting (`NEXT_PUBLIC_ADVISOR_URL`); without it the Advisor is
  hidden. Replies stream as server-sent events, one small JSON event each (quota, tool, text,
  error, done), so the page shows progress ("Ranking cards…") and the remaining quota as they
  arrive.
- The device keeps its conversation's text in the browser's storage so it survives a reload. It
  is cleared on sign-out, and a conversation idle for 7 days starts over, matching Memory's
  retention.
- Locally, `make agent` runs the agent next to `make demo`. It accepts the demo's dev user from a
  custom header and allows the site's origin (CORS) only when ADVISOR_LOCAL=1. The browser e2e
  test scripts the agent's stream, so CI never calls a model.

### Cost control

Each user gets **30 messages per day** (raised from 10 on 2026-09-30), reset at midnight US Eastern, enforced by the API
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
- **RAG over whole card pages for every question**: rejected for numbers and decisions (fees,
  offers, ranking, eligibility). Retrieval returns text, not computed values, and the model then
  reads and does the math itself, the failure the no-null rule exists to stop. Retrieval is
  planned only for fine print (below).

## Planned: answer feedback (with S5, the public site)

Each Advisor answer gets a 👍 / 👎, with an optional reason ("wrong information", "not what I
asked", "missing something"). The goal is not fine-tuning. It is finding bad answers, telling
whether the data, a tool, the prompt or the model caused them, and turning them into golden-set
cases (S8) and A/B metrics (S10).

- **Every turn**: the agent writes a turn record through the API, with the user's own token:
  question, answer, tools called and their results, model id, prompt and catalog versions, and
  trace id. It is stored under `USER#<id>` / `TURN#<time>#<id>` with a 7-day TTL, like Memory.
- **A rated turn** (`PUT /me/chat/turns/{id}/feedback`) is kept 90 days. The feedback control
  says so: sending feedback shares that conversation to improve the Advisor.
- **Unrated turns** expire after 7 days. Deleting the account deletes all of them.
- **Why this design**: content survives only where a user chose to share it. Logs never carry
  it (above). The tool results are what show whether a bad answer came from the data or the
  model.

## Planned: fine-print lookup (after the S8 golden set)

The catalog stores the facts ranking needs. It has no fine print, such as trip-delay insurance,
cell-phone protection or how a credit is enrolled, so today the Advisor says it doesn't know.
The plan, in order:

1. **Measure first**: the S8 golden set includes fine-print questions, to see how often they come
   up and fail.
2. **Card-scoped lookup, if they do**:
   - Each catalog version also stores the reviewed page text of each card, immutable, in the
     catalog bucket.
   - A tool `search_card_page(card_id, question)` returns the matching paragraphs of that one
     card's page. The Advisor quotes them with the page's fetch date.
   - Nearly every fine-print question names a card, and one card's page is a few thousand
     tokens, so this needs no embeddings or vector store.
3. **Benefit tags for cross-card questions** ("which cards have cell-phone protection?"): Scout
   extracts reviewed, structured benefit fields, and code filters them. Search can't promise a
   complete list; a filter over reviewed fields can.
4. **Full vector RAG only when the corpus outgrows this**, such as benefit-guide PDFs, full
   terms or more markets. That means Bedrock Knowledge Bases with S3 Vectors (OpenSearch
   Serverless has a high always-on minimum). `agentcore.json` already has a `knowledgeBases`
   slot.

Pages that robots.txt disallows (Amex terms) are never fetched; a person pastes them, as for the
offer terms.

## Consequences

- Catalog coverage stays at 53 open cards for v1; P1 cards, Barclays and more business cards come
  later.
- New reviewed data: the category mapping table, the point valuation table and the Amex ladders.
- The same ranking serves the chat and the web pages, so answers and pages always agree.
