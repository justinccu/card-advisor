from importlib import resources

import yaml
from pydantic import TypeAdapter

from card_rules.models import EligibilityRule, Market

_adapter = TypeAdapter(list[EligibilityRule])


def load_rules(market: Market = Market.US) -> list[EligibilityRule]:
    text = resources.files("card_rules.data").joinpath(f"rules_{market.lower()}.yaml").read_text()
    rules = _adapter.validate_python(yaml.safe_load(text))
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate rule ids in {market} rules")
    if any(r.market != market for r in rules):
        raise ValueError(f"rule with wrong market in {market} rules")
    return rules
