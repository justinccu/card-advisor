# Card Advisor (working name)

A US credit card and bank offer advisor: a public, non-LLM catalog for browsing and comparing cards, plus a conversational agent that recommends cards based on a user's profile and the cards they already hold.

## Language

### Catalog

**Market**:
A country whose cards, Issuers, and Eligibility Rules form a separate catalog (US first; TW later).

**Issuer**:
The bank or company that issues a Card Product (e.g. Chase, American Express).
_Avoid_: Bank (reserved for deposit-account offers)

**Card Product**:
A specific card offering in the catalog, such as Chase Sapphire Preferred. A Card Product closed to new applicants stays in the catalog (users can still hold it, and it still triggers Offer Rules) but is never recommended.
_Avoid_: Card (ambiguous), credit card

**Product Family**:
A set of an Issuer's Card Products that share Offer restrictions (e.g. Sapphire: Preferred and Reserve).
_Avoid_: Card line, series

**Offer**:
The sign-up bonus attached to a Card Product for a period of time, with its Minimum Spend and deadline. Classified as Public, Elevated, In-branch, or Targeted.
_Avoid_: Welcome bonus, sign-up bonus, 開卡禮 (as distinct terms)

**Elevated Offer**:
A publicly available Offer that is temporarily higher than the Card Product's usual Public Offer.
_Avoid_: Hidden offer

**Targeted Offer**:
An Offer shown only to specific people (mailers, pre-approval tools, logged-in pages); never published as catalog fact.
_Avoid_: Hidden offer

**Minimum Spend**:
The amount a cardholder must spend within a deadline after account opening to earn an Offer.

**Eligibility Rule**:
An Issuer's restriction, either an **Application Rule** (whether the user can be approved, e.g. Chase 5/24) or an **Offer Rule** (whether the user would earn the Offer, e.g. Amex once-per-lifetime). Each is **strict** (consistently enforced) or **soft** (inconsistently enforced; only ever a warning).

**Point Valuation**:
The dollar value assigned to one reward point: Conservative (cash/statement-credit value, the default) or Travel (transfer-partner estimate, opt-in).
_Avoid_: Point value, cpp (as an unqualified term)

**Catalog Snapshot**:
An immutable, versioned export of all published Card Products and Offers at a point in time.

### Users

**Applicant Profile**:
The facts about a user that affect eligibility: SSN/ITIN status, credit history length, approximate credit score, income range, spending pattern. Collected at sign-up or during conversation.
_Avoid_: User info, credit profile

**Held Card**:
A Card Product a user holds, with its open date and any Minimum Spend progress. Never includes a card number.
_Avoid_: My card, user card

**Wallet**:
The set of a user's Held Cards.
_Avoid_: Apple Wallet (unrelated)

**Wallet Attestation**:
What the user has confirmed about their Wallet's completeness: all cards opened since a date, all currently open cards, or full lifetime history with a given Issuer. Absence of a card only counts as evidence when an attestation covers it.
_Avoid_: Complete Wallet

**Eligibility Verdict**:
The result of evaluating Eligibility Rules for a user and Card Product, given separately for the application and for the Offer: Eligible, Ineligible, or Undetermined (when the Applicant Profile or Wallet Attestation doesn't cover a rule).
_Avoid_: Approved, qualified (we never predict approval)

**Recommendation**:
A ranked list of Card Products for an Applicant Profile and Wallet, computed against one Catalog Snapshot.

**Invite Code**:
A limited-use code, issued by an admin, required to create an account during the invite-only phase.

### Data sourcing

**Scout**:
The background agent that reads whitelisted sources and produces Proposed Changes.
_Avoid_: Crawler, scraper

**Proposed Change**:
A Scout finding (with source URL, extracted content, confidence) awaiting human review before it can enter the catalog.

**Data Point**:
An unverified user-reported observation (e.g. a Targeted Offer received); never treated as catalog fact.
