"""Find catalog cards by what people call them: "amex gold", "American Express Gold", "CSP",
"saphire preferred", "Amex" (every Amex card).

Mirrors web/src/lib/search.ts, the site's search box; keep the two in step. A card's words are
its name, id, aliases, and its bank's name and aliases (catalog snapshot `issuers`). A query
word matches a card word exactly, as a prefix ("plat"), or with a typo (one letter off in 4+
letters, two in 8+). Cards matching every query word come first; among them, one whose own name
the query covers entirely is the card meant.
"""

import re
from collections.abc import Iterable

# Words that don't tell cards apart: filler, and card networks ("Bilt Mastercard" must not
# match the Citi Secured Mastercard).
STOP_WORDS = {
    "a", "an", "and", "by", "card", "cards", "credit", "for", "from", "mastercard", "of",
    "signature", "the", "visa", "with",
}  # fmt: skip


def words(text: str) -> list[str]:
    text = text.lower().replace("+", " plus ")
    return [w for w in re.findall(r"[a-z0-9]+", text) if w not in STOP_WORDS]


def _distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def matches(query_word: str, word: str) -> bool:
    if query_word == word or (len(query_word) >= 2 and word.startswith(query_word)):
        return True
    if len(query_word) < 4 or abs(len(query_word) - len(word)) > 2:
        return False
    return _distance(query_word, word) <= (2 if len(query_word) >= 8 else 1)


def _issuer_words(card: dict, issuers: dict) -> set[str]:
    issuer = issuers.get(card["issuer_id"]) or {}
    names = [
        issuer.get("name", ""),
        *issuer.get("aliases", []),
        card["issuer_id"].replace("_", " "),
    ]
    return {w for name in names for w in words(name)}


def rank(query: str, cards: Iterable[dict], issuers: dict) -> list[tuple[dict, float, float]]:
    """(card, share of query words matched, share of the card's own name covered), best first;
    only cards matching at least half the query."""
    wanted = words(query)
    if not wanted:
        return []
    ranked = []
    for card in cards:
        bank = _issuer_words(card, issuers)
        names = [card["name"], *card.get("aliases", [])]
        vocabulary = bank | set(words(card["id"].replace("_", " ")))
        vocabulary |= {w for name in names for w in words(name)}
        hit = sum(1 for q in wanted if any(matches(q, w) for w in vocabulary))
        score = hit / len(wanted)
        if score < 0.5:
            continue
        # How much of the card's own name (bank words aside) the query covers.
        own_names = [set(words(name)) - bank for name in names]
        coverage = max(
            (
                sum(1 for w in own if any(matches(q, w) for q in wanted)) / len(own)
                for own in own_names
                if own
            ),
            default=0.0,
        )
        ranked.append((card, score, coverage))
    ranked.sort(key=lambda r: (-r[1], -r[2]))
    return ranked


def find(query: str, cards: dict[str, dict], issuers: dict) -> tuple[str, list[dict]]:
    """("one", [card]), ("several", cards) to ask which, ("closest", cards) when nothing matches
    every word, or ("none", []) when the catalog doesn't have it."""
    key = query.strip().lower()
    if key in cards:
        return "one", [cards[key]]
    ranked = rank(query, cards.values(), issuers)
    if not ranked:
        return "none", []
    full = [r for r in ranked if r[1] == 1]
    # Without a full match, only a confident one (2/3 of the words, the card's whole name) is
    # taken as meant: "amex green card for travel" is the Green, "bilt gold" is not the Gold.
    pool = full or [r for r in ranked if r[1] >= 2 / 3]
    whole = [r for r in pool if r[2] == 1]
    if len(whole) == 1:
        return "one", [whole[0][0]]
    if len(full) == 1:
        return "one", [full[0][0]]
    if full:
        return "several", [r[0] for r in full]
    return "closest", [r[0] for r in ranked]
