"""Names people search cards by, stamped into the Catalog Snapshot at publish.

Banks: catalog/seed/issuers.yaml ("Amex" for American Express). Cards: each seed card's
`aliases` ("CSP"). Both are copied on every publish path, so the site's search box and the
Advisor's card lookup read the same list from one versioned file.
"""

import yaml
from card_rules.catalog import CatalogCard, Issuer

from scout.annotate import SEED
from scout.seed import SeedCard

ISSUERS_PATH = SEED / "issuers.yaml"


class SearchNamesError(ValueError):
    pass


def load_issuers(path=ISSUERS_PATH) -> dict[str, Issuer]:
    return {k: Issuer.model_validate(v) for k, v in yaml.safe_load(path.read_text()).items()}


def stamp(
    cards: list[CatalogCard], seed: list[SeedCard], issuers: dict[str, Issuer]
) -> list[CatalogCard]:
    missing = sorted({c.issuer_id for c in cards} - set(issuers))
    if missing:
        raise SearchNamesError(f"no entry in {ISSUERS_PATH.name} for: {', '.join(missing)}")
    aliases = {s.id: s.aliases for s in seed}
    return [c.model_copy(update={"aliases": aliases.get(c.id, [])}) for c in cards]
