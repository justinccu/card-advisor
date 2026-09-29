"""Plain-English facts about each Eligibility Rule (ADR 0009).

Generated from the same fields `engine` evaluates, so what the Advisor says a rule counts is what
the engine counts. The Advisor explains rules only from these facts, never from the model's own
memory: asked about Chase 5/24 without them, it said closed cards and other banks' cards don't
count, and both do.
"""

from card_rules.models import (
    EligibilityRule,
    FamilyOpenRule,
    MaxOpenRule,
    OfferHistoryRule,
    VelocityRule,
)

_PRODUCTS = {
    "personal": "personal {} cards",
    "business": "business {} cards",
    "all": "every {} card",
}


def _span(rule: VelocityRule) -> str:
    return f"{rule.window_months} months" if rule.window_months else f"{rule.window_days} days"


def _counts(label: str, counted: bool) -> str:
    return f"{label} {'count' if counted else 'do not count'}."


def how_it_counts(rule: EligibilityRule, names: dict[str, str] | None = None) -> list[str]:
    """What the rule looks at, one fact per line. `names` maps card ids to display names."""
    names = names or {}
    issuer = rule.issuer_id

    if isinstance(rule, VelocityRule):
        source = "from any bank" if rule.scope == "all_issuers" else f"from {issuer} only"
        return [
            f"Counts new cards opened {source} in the last {_span(rule)}; "
            f"an application is denied at {rule.limit} or more.",
            "A card counts by the date it was opened: "
            "closing it does not remove it from the count.",
            _counts("Authorized-user cards", rule.counts_authorized_user),
            _counts("Business cards", rule.counts_business),
            _counts("Charge cards", rule.counts_charge_cards),
        ]
    if isinstance(rule, MaxOpenRule):
        return [
            f"At most {rule.limit} {issuer} cards may be open at once; closed cards do not count.",
            "Authorized-user cards do not count.",
            _counts("Business cards", rule.counts_business),
            _counts("Charge cards", rule.counts_charge_cards),
        ]
    if isinstance(rule, FamilyOpenRule):
        return [
            f"No welcome offer while another personal {rule.family} card from {issuer} is open.",
            "Closed cards and authorized-user cards do not count.",
        ]
    if isinstance(rule, OfferHistoryRule):
        if rule.target == "product":
            what = "this same card"
        elif rule.target == "products":
            what = "any of: " + ", ".join(names.get(p, p) for p in rule.products)
        else:
            what = f"any {rule.family} card from {issuer}"
        if rule.basis == "held":
            when = (
                "ever held"
                if rule.lookback_months is None
                else f"held (open, or closed less than {rule.lookback_months} months ago)"
            )
            facts = [f"No welcome offer if you have {when} {what}."]
        else:
            when = (
                "ever earned"
                if rule.lookback_months is None
                else f"earned in the last {rule.lookback_months} months"
            )
            facts = [f"No welcome offer if you have {when} the welcome offer on {what}."]
        if rule.for_product:
            facts.append(f"Applies to {names.get(rule.for_product, rule.for_product)} only.")
        facts.append("Authorized-user cards do not count.")
        return facts
    raise TypeError(f"no explanation for {type(rule).__name__}")


def explain(rule: EligibilityRule, names: dict[str, str] | None = None) -> dict:
    decides = "approval" if isinstance(rule, VelocityRule | MaxOpenRule) else "welcome offer"
    return {
        "rule_id": rule.id,
        "issuer_id": rule.issuer_id,
        "summary": rule.description,
        "decides": decides,
        "applies_to": _PRODUCTS[rule.applies_to_products].format(rule.issuer_id)
        + ("" if rule.applies_to_charge_cards else ", not charge cards"),
        "how_it_counts": how_it_counts(rule, names),
        "enforcement": "strict: cards are marked Ineligible"
        if rule.strength == "strict"
        else "soft: only a warning, because the bank enforces it inconsistently",
        "source": "the issuer's own terms"
        if rule.confidence == "official"
        else "applicants' reported results (the bank doesn't publish it)",
        "source_url": str(rule.source_url),
        "verified_on": rule.verified_on.isoformat(),
    }
