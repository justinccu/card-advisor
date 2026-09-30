import pytest
from card_rules.catalog import CatalogCard, Issuer
from scout import publish, search_names
from scout.seed import SeedCard


def card(id_, issuer="amex"):
    return CatalogCard(id=id_, issuer_id=issuer, name=id_, url="https://x")


def seed(id_, aliases=()):
    return SeedCard(
        id=id_, issuer_id="amex", name=id_, url="https://x", priority="P0", aliases=list(aliases)
    )


def test_every_bank_in_the_catalog_has_search_names():
    issuers = search_names.load_issuers()
    assert issuers["amex"].name == "American Express" and "Amex" in issuers["amex"].aliases
    with pytest.raises(search_names.SearchNamesError, match="bilt"):
        search_names.stamp([card("x", issuer="bilt")], [], issuers)


def test_card_aliases_come_from_the_seed():
    issuers = {"amex": Issuer(name="American Express", aliases=["Amex"])}
    [stamped] = search_names.stamp([card("amex_gold")], [seed("amex_gold", ["Amex Gold"])], issuers)
    assert stamped.aliases == ["Amex Gold"]


def test_a_change_to_search_names_publishes_a_new_version(tmp_path):
    issuers = {"amex": Issuer(name="American Express", aliases=["Amex"])}
    first = publish.publish([card("amex_gold")], tmp_path, issuers=issuers)
    assert publish.publish([card("amex_gold")], tmp_path, issuers=issuers) is None  # unchanged
    renamed = {"amex": Issuer(name="American Express", aliases=["Amex", "AmEx Co"])}
    second = publish.publish([card("amex_gold")], tmp_path, issuers=renamed)
    assert first.name == "v1.1.json" and second.name == "v1.2.json"
    assert '"AmEx Co"' in second.read_text()
