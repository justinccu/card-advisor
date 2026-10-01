"""Deterministic Eligibility Verdicts (ADR 0001).

Pure functions of (Card Product, Applicant Profile, Wallet, rules, as_of): no clock, no I/O,
so a Recommendation can be replayed exactly against a Catalog Snapshot.
"""

from collections.abc import Iterable
from datetime import date

from card_rules.dates import add_months, age_out_date, window_start
from card_rules.models import (
    ApplicantProfile,
    CardProduct,
    EligibilityRule,
    Evaluation,
    FamilyOpenRule,
    HeldCard,
    MaxOpenRule,
    OfferHistoryRule,
    ProductOpenRule,
    Reason,
    Status,
    VelocityRule,
    Verdict,
    Wallet,
)

# Minimum-spend windows run up to ~12 months, so a bonus on a card opened more than this
# long before a lookback window began cannot have landed inside it.
BONUS_EARN_MAX_MONTHS = 12


def evaluate(
    product: CardProduct,
    profile: ApplicantProfile,
    wallet: Wallet,
    rules: Iterable[EligibilityRule],
    as_of: date,
) -> Evaluation:
    application: list[tuple[EligibilityRule | None, Reason]] = [(None, _tax_id(product, profile))]
    offer: list[tuple[EligibilityRule | None, Reason]] = []

    for rule in rules:
        if not _applies(rule, product):
            continue
        match rule:
            case VelocityRule():
                application.append((rule, _velocity(rule, wallet, as_of)))
            case MaxOpenRule():
                application.append((rule, _max_open(rule, wallet)))
            case ProductOpenRule():
                application.append((rule, _product_open(rule, product, wallet)))
            case FamilyOpenRule():
                offer.append((rule, _family_open(rule, wallet)))
            case OfferHistoryRule():
                offer.append((rule, _offer_history(rule, product, wallet, as_of)))

    return Evaluation(
        card_product_id=product.id,
        as_of=as_of,
        application=_combine(application),
        offer=_combine(offer),
    )


def _applies(rule: EligibilityRule, product: CardProduct) -> bool:
    if rule.market != product.market or rule.issuer_id != product.issuer_id:
        return False
    if rule.applies_to_products == "personal" and product.is_business:
        return False
    if rule.applies_to_products == "business" and not product.is_business:
        return False
    if product.is_charge_card and not rule.applies_to_charge_cards:
        return False
    if product.id in rule.not_for_products:
        return False
    if isinstance(rule, OfferHistoryRule) and rule.for_product:
        return product.id == rule.for_product
    if isinstance(rule, ProductOpenRule | FamilyOpenRule | OfferHistoryRule) and rule.family:
        return product.family == rule.family
    return True


def _combine(results: list[tuple[EligibilityRule | None, Reason]]) -> Verdict:
    reasons: list[Reason] = []
    warnings: list[Reason] = []
    for rule, reason in results:
        if rule is not None and rule.strength == "soft":
            if reason.status is Status.INELIGIBLE:
                warnings.append(reason)
            continue
        reasons.append(reason)

    statuses = {r.status for r in reasons}
    if Status.INELIGIBLE in statuses:
        status = Status.INELIGIBLE
    elif Status.UNDETERMINED in statuses:
        status = Status.UNDETERMINED
    else:
        status = Status.ELIGIBLE
    return Verdict(status=status, reasons=reasons, warnings=warnings)


def _reason(rule: EligibilityRule, status: Status, message: str, **kw) -> Reason:
    return Reason(
        rule_id=rule.id,
        status=status,
        message=message,
        confidence=rule.confidence,
        source_url=str(rule.source_url),
        **kw,
    )


def _tax_id(product: CardProduct, profile: ApplicantProfile) -> Reason:
    accepted = ", ".join(sorted(product.accepted_tax_ids))
    if profile.tax_id is None:
        status, message = (
            Status.UNDETERMINED,
            f"Need the applicant's tax ID type (accepts {accepted}).",
        )
    elif profile.tax_id in product.accepted_tax_ids:
        status, message = Status.ELIGIBLE, f"Applicant's {profile.tax_id} is accepted."
    else:
        status, message = Status.INELIGIBLE, f"Requires one of: {accepted}."
    return Reason(rule_id="tax_id", status=status, message=message, confidence="official")


def _covers(wallet: Wallet, issuer_id: str, since: date) -> bool:
    """Whether the Wallet's attestations rule out a missing card opened after `since`."""
    if issuer_id in wallet.full_history_issuers:
        return True
    return wallet.complete_since is not None and wallet.complete_since <= since


def _velocity(rule: VelocityRule, wallet: Wallet, as_of: date) -> Reason:
    window = {"months": rule.window_months, "days": rule.window_days}
    start = window_start(as_of, **window)
    counted = sorted(
        c.opened_on
        for c in wallet.cards
        if start < c.opened_on <= as_of
        and (rule.scope == "all_issuers" or c.issuer_id == rule.issuer_id)
        and (rule.counts_authorized_user or not c.is_authorized_user)
        and (rule.counts_business or not c.is_business)
        and (rule.counts_charge_cards or not c.is_charge_card)
    )
    span = f"{rule.window_months} months" if rule.window_months else f"{rule.window_days} days"
    tally = f"{len(counted)} counted card(s) opened in the last {span} (limit {rule.limit})"

    if len(counted) >= rule.limit:
        # The (count - limit + 1) oldest cards must age out before the user is under the limit.
        retry = age_out_date(counted[len(counted) - rule.limit], **window)
        return _reason(rule, Status.INELIGIBLE, f"{rule.description}: {tally}.", retry_after=retry)

    covered = (
        _covers(wallet, rule.issuer_id, start)
        if rule.scope == "same_issuer"
        else wallet.complete_since is not None and wallet.complete_since <= start
    )
    if not covered:
        return _reason(
            rule,
            Status.UNDETERMINED,
            f"{rule.description}: {tally}, but the Wallet isn't confirmed complete "
            f"back to {start.isoformat()}.",
        )
    return _reason(rule, Status.ELIGIBLE, f"{rule.description}: {tally}.")


def _max_open(rule: MaxOpenRule, wallet: Wallet) -> Reason:
    open_cards = [
        c
        for c in wallet.cards
        if c.is_open
        and c.issuer_id == rule.issuer_id
        and not c.is_authorized_user
        and (rule.counts_business or not c.is_business)
        and (rule.counts_charge_cards or not c.is_charge_card)
    ]
    tally = f"{len(open_cards)} open card(s) counted (limit {rule.limit})"
    if len(open_cards) >= rule.limit:
        return _reason(rule, Status.INELIGIBLE, f"{rule.description}: {tally}.")
    if not wallet.includes_all_open_cards:
        return _reason(
            rule, Status.UNDETERMINED, f"{rule.description}: {tally}; open cards not confirmed."
        )
    return _reason(rule, Status.ELIGIBLE, f"{rule.description}: {tally}.")


def _product_open(rule: ProductOpenRule, product: CardProduct, wallet: Wallet) -> Reason:
    if any(
        c.is_open and c.card_product_id == product.id and not c.is_authorized_user
        for c in wallet.cards
    ):
        return _reason(rule, Status.INELIGIBLE, f"{rule.description}: this card is already open.")
    if not wallet.includes_all_open_cards:
        return _reason(rule, Status.UNDETERMINED, f"{rule.description}: open cards not confirmed.")
    return _reason(rule, Status.ELIGIBLE, f"{rule.description}: this card isn't open.")


def _family_open(rule: FamilyOpenRule, wallet: Wallet) -> Reason:
    blocking = [
        c
        for c in wallet.cards
        if c.is_open
        and c.issuer_id == rule.issuer_id
        and c.family == rule.family
        and not c.is_business
        and not c.is_authorized_user
    ]
    if blocking:
        return _reason(
            rule, Status.INELIGIBLE, f"{rule.description}: a {rule.family} card is currently open."
        )
    if not wallet.includes_all_open_cards:
        return _reason(rule, Status.UNDETERMINED, f"{rule.description}: open cards not confirmed.")
    return _reason(rule, Status.ELIGIBLE, f"{rule.description}: no open {rule.family} card.")


def _relevant(rule: OfferHistoryRule, product: CardProduct, card: HeldCard) -> bool:
    if card.issuer_id != rule.issuer_id or card.is_authorized_user:
        return False
    if rule.target == "product":
        return card.card_product_id == product.id
    if rule.target == "products":
        return card.card_product_id in rule.products
    return card.family == rule.family


def _offer_history(
    rule: OfferHistoryRule, product: CardProduct, wallet: Wallet, as_of: date
) -> Reason:
    lookback = rule.lookback_months
    start = add_months(as_of, -lookback) if lookback is not None else None
    period = "ever" if start is None else f"since {start.isoformat()}"
    relevant = [c for c in wallet.cards if _relevant(rule, product, c)]

    if rule.basis == "held":
        hits = [c for c in relevant if start is None or c.closed_on is None or c.closed_on > start]
        if hits:
            still_open = any(c.closed_on is None for c in hits)
            retry = (
                None
                if start is None or still_open
                else add_months(max(c.closed_on for c in hits), lookback)
            )
            return _reason(
                rule, Status.INELIGIBLE, f"{rule.description}: held {period}.", retry_after=retry
            )
        needed_since = start
    else:
        earned = [
            c.bonus_received_on
            for c in relevant
            if c.bonus_received_on and (start is None or c.bonus_received_on > start)
        ]
        if earned:
            retry = None if start is None else add_months(max(earned), lookback)
            return _reason(
                rule,
                Status.INELIGIBLE,
                f"{rule.description}: bonus earned {period}.",
                retry_after=retry,
            )
        earliest_possible = None if start is None else add_months(start, -BONUS_EARN_MAX_MONTHS)
        unknown = [
            c
            for c in relevant
            if c.bonus_received_on is None
            and (earliest_possible is None or c.opened_on > earliest_possible)
        ]
        if unknown:
            return _reason(
                rule,
                Status.UNDETERMINED,
                f"{rule.description}: held a matching card; need whether and when its bonus "
                f"was earned.",
            )
        needed_since = earliest_possible

    covered = (
        rule.issuer_id in wallet.full_history_issuers
        if needed_since is None
        else _covers(wallet, rule.issuer_id, needed_since)
    )
    if rule.basis == "held" and needed_since is not None:
        covered = covered and wallet.includes_all_open_cards
    if not covered:
        needed = "lifetime" if needed_since is None else f"since {needed_since.isoformat()}"
        return _reason(
            rule,
            Status.UNDETERMINED,
            f"{rule.description}: no matching card listed, but card history {needed} "
            f"isn't confirmed.",
        )
    return _reason(rule, Status.ELIGIBLE, f"{rule.description}: no matching card {period}.")
