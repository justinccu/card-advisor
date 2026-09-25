import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime

from scout import boilerplate, publish, review
from scout.bedrock import DEFAULT_MODEL, PRICES, BudgetExceeded, Ledger, cost_usd
from scout.extract import MAX_OUTPUT_TOKENS, PROMPT_OVERHEAD_TOKENS, extract
from scout.fetch import Fetcher, RobotsDenied, load_cached, save
from scout.seed import CACHE_DIR, load_seed, select

# Output size observed in the 2026-09-24 Kimi tool-call test, scaled to a full card; used only
# for the "expected" column. The budget guard always uses the worst case (MAX_OUTPUT_TOKENS).
EXPECTED_OUTPUT_TOKENS = 1500


def cmd_fetch(args: argparse.Namespace) -> None:
    cards = select(load_seed(), priority=args.priority, only=args.only)
    fetcher = Fetcher(browser_fallback=not args.no_browser)
    unchanged = changed = failed = 0
    try:
        for card in cards:
            previous = load_cached(card.id, CACHE_DIR)
            try:
                result = fetcher.fetch(card.url)
            except RobotsDenied:
                print(f"  {card.id:38} SKIP robots.txt disallows")
                failed += 1
                continue
            except Exception as e:  # one bad page must not stop the batch
                print(f"  {card.id:38} FAIL {type(e).__name__}: {e}")
                failed += 1
                continue
            if not result.text:
                print(f"  {card.id:38} FAIL {result.note}")
                failed += 1
                continue
            same = previous is not None and previous[0]["content_hash"] == result.content_hash
            unchanged += same
            changed += not same
            save(result, card.id, CACHE_DIR)
            print(
                f"  {card.id:38} {result.method:7} {result.status} "
                f"{len(result.text):6} chars ~{len(result.text) // 4:5} tok "
                f"{'unchanged' if same else 'new/changed'}"
                + (f"  ({result.note})" if result.note else "")
            )
    finally:
        fetcher.close()
    print(f"\n{len(cards)} cards: {changed} new/changed, {unchanged} unchanged, {failed} failed")


def _prompt_texts(cards) -> dict[str, tuple[dict, str, str]]:
    """card_id -> (meta, full page text, boilerplate-stripped prompt text)."""
    cached = {c.id: load_cached(c.id, CACHE_DIR) for c in cards}
    missing = [cid for cid, v in cached.items() if v is None]
    if missing:
        raise SystemExit(f"not fetched yet (run `scout fetch`): {', '.join(missing)}")
    # Learn each issuer's site chrome from every cached page of that issuer, not just this batch.
    by_issuer: dict[str, list[str]] = defaultdict(list)
    for card in load_seed():
        hit = load_cached(card.id, CACHE_DIR)
        if hit:
            by_issuer[card.issuer_id].append(hit[1])
    chrome = {issuer: boilerplate.shared_lines(pages) for issuer, pages in by_issuer.items()}
    return {
        c.id: (
            cached[c.id][0],
            cached[c.id][1],
            boilerplate.strip(cached[c.id][1], chrome[c.issuer_id]),
        )
        for c in cards
    }


def cmd_extract(args: argparse.Namespace) -> None:
    cards = select(load_seed(), priority=args.priority, only=args.only)
    texts = _prompt_texts(cards)
    ledger = Ledger(CACHE_DIR / "spend.jsonl")

    raw_tok = sum(len(full) // 4 for _, full, _ in texts.values())
    in_tok = sum(len(p) // 4 + PROMPT_OVERHEAD_TOKENS for _, _, p in texts.values())
    expected = sum(
        cost_usd(args.model, len(p) // 4 + PROMPT_OVERHEAD_TOKENS, EXPECTED_OUTPUT_TOKENS)
        for _, _, p in texts.values()
    )
    worst = sum(
        cost_usd(args.model, len(p) // 4 + PROMPT_OVERHEAD_TOKENS, MAX_OUTPUT_TOKENS)
        for _, _, p in texts.values()
    )
    print(
        f"{len(cards)} cards with {args.model}\n"
        f"  input tokens ~{in_tok:,} (page text ~{raw_tok:,} before stripping site chrome)\n"
        f"  expected ${expected:.3f}, worst case ${worst:.3f}; "
        f"spent so far ${ledger.total_usd():.4f} of ${ledger.budget_usd:.2f} cap"
    )
    if not args.live:
        print("dry run: no model calls made (add --live to extract)")
        return

    import boto3
    from botocore.exceptions import NoCredentialsError, SSOTokenLoadError, TokenRetrievalError

    client = boto3.client("bedrock-runtime")
    run_dir = CACHE_DIR / "runs" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for card in cards:
        meta, full, prompt = texts[card.id]
        try:
            change = extract(
                card,
                page_text=full,
                prompt_text=prompt,
                content_hash=meta["content_hash"],
                client=client,
                model_id=args.model,
                ledger=ledger,
            )
        except BudgetExceeded as e:
            print(f"STOP: {e}")
            break
        except (NoCredentialsError, TokenRetrievalError, SSOTokenLoadError) as e:
            # Every remaining card would fail the same way; stop instead of retrying each.
            print(
                f"STOP: AWS credentials unavailable ({e}). "
                "Run `aws login --profile card-advisor` and retry."
            )
            break
        except Exception as e:  # one bad card must not stop the batch
            print(f"  {card.id:38} FAIL {type(e).__name__}: {e}")
            continue
        change.save(run_dir)
        flagged = [c.path for c in change.checks if c.status in ("unverified", "missing_evidence")]
        print(
            f"  {card.id:38} ${change.cost_usd:.4f} verified {change.verified_ratio:5.0%}"
            + (f"  flagged: {', '.join(flagged)}" if flagged else "")
        )
    print(f"\nrun saved to {run_dir}; total spent ${ledger.total_usd():.4f}")


REVIEWS_DIR = CACHE_DIR / "reviews"


def cmd_review(args: argparse.Namespace) -> None:
    run_dir = CACHE_DIR / "runs" / args.run if args.run else review.latest_run(CACHE_DIR / "runs")
    done = review.load_reviews(REVIEWS_DIR)
    changes = [json.loads(p.read_text()) for p in sorted(run_dir.glob("*.json"))]
    pending = [
        c
        for c in changes
        if (not args.only or c["card_id"] in args.only)
        and done.get(c["card_id"], {}).get("content_hash") != c["content_hash"]
    ]
    print(
        f"run {run_dir.name}: {len(pending)} to review, {len(changes) - len(pending)} already done"
    )
    try:
        for i, change in enumerate(pending, 1):
            print(f"\n── {i}/{len(pending)} " + "─" * 60)
            page = load_cached(change["card_id"], CACHE_DIR)
            result = review.decide(
                change, page[1] if page else "", run=run_dir.name, ask=input, say=print
            )
            if result:
                result.save(REVIEWS_DIR)
                print(f"  → {result.decision}")
    except (KeyboardInterrupt, EOFError):
        print("\nstopped; progress saved")
    cmd_stats(args)


def cmd_stats(args: argparse.Namespace) -> None:
    s = review.accuracy(review.load_reviews(REVIEWS_DIR))
    print(
        f"\n{s['cards_approved']} approved, {s['cards_rejected']} rejected; "
        f"{s['fields_reviewed']} fields reviewed, {s['fields_edited']} edited "
        f"→ {s['accepted_unchanged']:.1%} accepted unchanged"
    )


def cmd_publish(args: argparse.Namespace) -> None:
    cards = publish.build(load_seed(), review.load_reviews(REVIEWS_DIR))
    path = publish.publish(cards)
    open_cards = sum(c.availability == "open" for c in cards)
    if path is None:
        print(f"catalog unchanged ({len(cards)} cards); no new snapshot written")
    else:
        print(
            f"wrote {path.relative_to(publish.REPO_ROOT)}: {open_cards} open + "
            f"{len(cards) - open_cards} closed cards"
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="scout")
    sub = parser.add_subparsers(required=True)

    fetch = sub.add_parser("fetch", help="fetch Issuer pages into the local cache ($0)")
    fetch.add_argument("--priority", default="P0", choices=["P0", "P1"])
    fetch.add_argument("--only", type=lambda s: s.split(","), help="comma-separated card ids")
    fetch.add_argument("--no-browser", action="store_true", help="never fall back to Playwright")
    fetch.set_defaults(func=cmd_fetch)

    ext = sub.add_parser("extract", help="extract Proposed Changes (dry run unless --live)")
    ext.add_argument("--priority", default="P0", choices=["P0", "P1"])
    ext.add_argument("--only", type=lambda s: s.split(","), help="comma-separated card ids")
    ext.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(PRICES))
    ext.add_argument("--live", action="store_true", help="actually call Bedrock (costs money)")
    ext.set_defaults(func=cmd_extract)

    rev = sub.add_parser("review", help="approve/edit/reject Proposed Changes ($0)")
    rev.add_argument("--run", help="run id under catalog/.cache/runs (default: latest)")
    rev.add_argument("--only", type=lambda s: s.split(","), help="comma-separated card ids")
    rev.set_defaults(func=cmd_review)

    sub.add_parser("stats", help="extraction accuracy from reviews").set_defaults(func=cmd_stats)
    sub.add_parser("publish", help="write the next Catalog Snapshot").set_defaults(func=cmd_publish)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
