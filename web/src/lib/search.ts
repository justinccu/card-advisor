// Find cards by what people call them: "amex gold", "American Express Gold", "CSP",
// "saphire preferred", "Amex" (every Amex card). Mirrors the Advisor's card lookup
// (agent/app/Advisor/advisor/search.py); keep the two in step.
//
// A card's words are its name, id, aliases, and its bank's name and aliases (the snapshot's
// `issuers`). A query word matches exactly, as a prefix (so results follow typing: "plat"), or
// with a typo (one letter off in 4+ letters, two in 8+). Cards matching every word come first,
// the one whose own name the query covers most at the top.
import type { CatalogCard, Issuer } from "./types";

// Filler, and card networks: "Bilt Mastercard" must not match the Citi Secured Mastercard.
const STOP_WORDS = new Set([
  "a", "an", "and", "by", "card", "cards", "credit", "for", "from", "mastercard", "of",
  "signature", "the", "visa", "with",
]);

export function words(text: string): string[] {
  return (text.toLowerCase().replaceAll("+", " plus ").match(/[a-z0-9]+/g) ?? []).filter(
    (w) => !STOP_WORDS.has(w),
  );
}

function distance(a: string, b: string): number {
  const row = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    let prev = row[0];
    row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const next = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = row[j];
      row[j] = next;
    }
  }
  return row[b.length];
}

export function matches(queryWord: string, word: string): boolean {
  if (queryWord === word || (queryWord.length >= 2 && word.startsWith(queryWord))) return true;
  if (queryWord.length < 4 || Math.abs(queryWord.length - word.length) > 2) return false;
  return distance(queryWord, word) <= (queryWord.length >= 8 ? 2 : 1);
}

type Ranked = { card: CatalogCard; score: number; coverage: number };

function issuerWords(card: CatalogCard, issuers: Record<string, Issuer>): Set<string> {
  const issuer = issuers[card.issuer_id];
  const names = [issuer?.name ?? "", ...(issuer?.aliases ?? []), card.issuer_id.replaceAll("_", " ")];
  return new Set(names.flatMap(words));
}

/** Cards matching at least half the query: share of query words matched, then share of the
 *  card's own name (bank words aside) the query covers. */
function rank(query: string, cards: CatalogCard[], issuers: Record<string, Issuer>): Ranked[] {
  const wanted = words(query);
  if (!wanted.length) return [];
  const ranked: Ranked[] = [];
  for (const card of cards) {
    const bank = issuerWords(card, issuers);
    const names = [card.name, ...(card.aliases ?? [])];
    const vocabulary = new Set([...bank, ...words(card.id.replaceAll("_", " ")), ...names.flatMap(words)]);
    const hit = wanted.filter((q) => [...vocabulary].some((w) => matches(q, w))).length;
    const score = hit / wanted.length;
    if (score < 0.5) continue;
    const coverage = Math.max(
      0,
      ...names
        .map((name) => words(name).filter((w) => !bank.has(w)))
        .filter((own) => own.length)
        .map((own) => own.filter((w) => wanted.some((q) => matches(q, w))).length / own.length),
    );
    ranked.push({ card, score, coverage });
  }
  return ranked.sort((a, b) => b.score - a.score || b.coverage - a.coverage);
}

/** Cards for a search box, best first. `exact` is false when nothing matched every word and
 *  these are only the closest. An empty query returns the cards unchanged. */
export function searchCards(
  query: string,
  cards: CatalogCard[],
  issuers: Record<string, Issuer>,
): { cards: CatalogCard[]; exact: boolean } {
  if (!words(query).length) return { cards, exact: true };
  const ranked = rank(query, cards, issuers);
  const full = ranked.filter((r) => r.score === 1);
  return full.length
    ? { cards: full.map((r) => r.card), exact: true }
    : { cards: ranked.map((r) => r.card), exact: false };
}
