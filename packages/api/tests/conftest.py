import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

# Settings read the environment at import time: point the app at a small fixture catalog
# before anything imports card_api.
_catalog = Path(tempfile.mkdtemp()) / "snapshot.json"
os.environ["APP_ENV"] = "local"
os.environ["CATALOG_PATH"] = str(_catalog)
os.environ.pop("TABLE_NAME", None)
os.environ.pop("CATALOG_BUCKET", None)

from card_rules.catalog import CatalogCard, CatalogSnapshot, Offer  # noqa: E402
from card_rules.models import Market, TaxId  # noqa: E402


def _card(id_, issuer, name, **kw):
    return CatalogCard(id=id_, issuer_id=issuer, name=name, url=f"https://example.com/{id_}", **kw)


CARDS = [
    _card(
        "chase_sapphire_preferred",
        "chase",
        "Sapphire Preferred",
        family="sapphire",
        annual_fee_usd=95,
        offer=Offer(
            amount_disclosed=True,
            amount=75000,
            unit="points",
            min_spend_usd=5000,
            spend_window_months=3,
        ),
    ),
    _card(
        "chase_freedom_unlimited",
        "chase",
        "Freedom Unlimited",
        accepted_tax_ids=frozenset({TaxId.SSN, TaxId.ITIN}),
    ),
    _card("citi_double_cash", "citi", "Double Cash"),
    _card("amex_blue_cash_everyday", "amex", "Blue Cash Everyday"),
    _card("c1_venture_x", "capital_one", "Venture X"),
    _card("discover_it_cash_back", "discover", "Discover it"),
    _card(
        "amex_green", "amex", "Green", availability="closed_to_new_applicants", is_charge_card=True
    ),
]
_catalog.write_text(
    CatalogSnapshot(
        version="1.1", market=Market.US, generated_at=datetime.now(UTC), cards=CARDS
    ).model_dump_json()
)
