import argparse
import json
import os
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime

from card_rules.catalog import CatalogSnapshot

from scout import boilerplate, compare, overrides, publish, release, report, review
from scout.bedrock import DEFAULT_MODEL, PRICES, BudgetExceeded, Ledger, cost_usd
from scout.evidence import check_card
from scout.extract import (
    MAX_OUTPUT_TOKENS,
    PROMPT_OVERHEAD_TOKENS,
    InvalidExtraction,
    Source,
    extract,
    to_change,
)
from scout.fetch import Fetcher, RobotsDenied, is_variant, load_cached, save
from scout.schema import ExtractedCard
from scout.seed import CACHE_DIR, load_seed, select

# Output size observed in the 2026-09-24 Kimi tool-call test, scaled to a full card; used only
# for the "expected" column. The budget guard always uses the worst case (MAX_OUTPUT_TOKENS).
EXPECTED_OUTPUT_TOKENS = 1500


def _fetch_one(fetcher: Fetcher, key: str, url: str) -> str:
    """Fetch one page into pages/<key>/. Returns "changed" | "unchanged" | "failed" | "blocked".

    A blocked or empty fetch never overwrites what's cached: stale-but-real beats nothing.
    """
    previous = load_cached(key, CACHE_DIR)
    try:
        result = fetcher.fetch(url)
    except RobotsDenied:
        print(f"  {key:44} SKIP robots.txt disallows")
        return "failed"
    except Exception as e:  # one bad page must not stop the batch
        print(f"  {key:44} FAIL {type(e).__name__}: {e}")
        return "failed"
    if not result.text:
        label = "BLOCKED" if result.blocked else "FAIL"
        print(f"  {key:44} {label} {result.note} (cache kept)")
        return "blocked" if result.blocked else "failed"
    same = previous is not None and previous[0]["content_hash"] == result.content_hash
    save(result, key, CACHE_DIR)
    flag = ""
    if is_variant(result.variant):
        flag = f"  VARIANT hidden-in-render={result.variant['hidden_in_render']}"
    print(
        f"  {key:44} {result.method:7} {result.status} {len(result.text):6} chars "
        f"{'unchanged' if same else 'new/changed'}{flag}"
        + (f"  ({result.note})" if result.note else "")
    )
    return "unchanged" if same else "changed"


def cmd_fetch(args: argparse.Namespace) -> None:
    cards = select(load_seed(), priority=args.priority, only=args.only)
    fetcher = Fetcher(render=not args.no_browser)
    counts: dict[str, int] = {}
    try:
        for card in cards:
            jobs = [(card.id, card.url)] + [
                (f"{card.id}/variants/{i}", u) for i, u in enumerate(card.variant_urls)
            ]
            for key, url in jobs:
                outcome = _fetch_one(fetcher, key, url)
                counts[outcome] = counts.get(outcome, 0) + 1
    finally:
        fetcher.close()
    print(f"\n{len(cards)} cards: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))


def _sources(cards) -> list[tuple]:
    """(card, Source, meta, full page text, prompt text) for each cached page of each card: the
    main page (required) plus any fetched campaign variants."""
    missing = [c.id for c in cards if load_cached(c.id, CACHE_DIR) is None]
    if missing:
        raise SystemExit(f"not fetched yet (run `scout fetch`): {', '.join(missing)}")
    # Learn each issuer's site chrome from every cached main page of that issuer.
    by_issuer: dict[str, list[str]] = defaultdict(list)
    for card in load_seed():
        hit = load_cached(card.id, CACHE_DIR)
        if hit:
            by_issuer[card.issuer_id].append(hit[1])
    chrome = {issuer: boilerplate.shared_lines(pages) for issuer, pages in by_issuer.items()}

    out = []
    for c in cards:
        pages = [(c.id, c.url, "fresh")] + [
            (f"{c.id}/variants/{i}", u, "campaign") for i, u in enumerate(c.variant_urls)
        ]
        for key, url, profile in pages:
            hit = load_cached(key, CACHE_DIR)
            if hit is None:
                print(f"  {key}: not fetched, skipped")
                continue
            meta, full = hit
            if meta.get("method") != "browser":
                # Architecture rule: model input is rendered visible text, never raw HTML.
                print(f"  {key}: not a rendered page ({meta.get('method')}), skipped; re-fetch")
                continue
            src = Source(key, url, profile, meta.get("fetched_at"), meta.get("variant"))
            out.append((c, src, meta, full, boilerplate.strip(full, chrome[c.issuer_id])))
    return out


def cmd_extract(args: argparse.Namespace) -> None:
    cards = select(load_seed(), priority=args.priority, only=args.only)
    items = _sources(cards)
    ledger = Ledger(CACHE_DIR / "spend.jsonl")

    raw_tok = sum(len(full) // 4 for *_, full, _ in items)
    in_tok = sum(len(p) // 4 + PROMPT_OVERHEAD_TOKENS for *_, p in items)
    expected = sum(
        cost_usd(args.model, len(p) // 4 + PROMPT_OVERHEAD_TOKENS, EXPECTED_OUTPUT_TOKENS)
        for *_, p in items
    )
    worst = sum(
        cost_usd(args.model, len(p) // 4 + PROMPT_OVERHEAD_TOKENS, MAX_OUTPUT_TOKENS)
        for *_, p in items
    )
    print(
        f"{len(cards)} cards, {len(items)} pages with {args.model}\n"
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
    for card, src, meta, full, prompt in items:
        try:
            change = extract(
                card,
                page_text=full,
                prompt_text=prompt,
                content_hash=meta["content_hash"],
                client=client,
                model_id=args.model,
                ledger=ledger,
                source=src,
            )
        except BudgetExceeded as e:
            print(f"STOP: {e}")
            break
        except (NoCredentialsError, TokenRetrievalError, SSOTokenLoadError) as e:
            # Every remaining card would fail the same way; stop instead of retrying each.
            print(
                f"STOP: AWS credentials unavailable ({e}). "
                f"Run `aws login --profile {os.environ.get('AWS_PROFILE', '<profile>')}` and retry."
            )
            break
        except InvalidExtraction as e:
            path = e.save(run_dir)
            print(f"  {src.key:38} INVALID {e} -> {path.name}")
            continue
        except Exception as e:  # one bad card must not stop the batch
            print(f"  {src.key:38} FAIL {type(e).__name__}: {e}")
            continue
        change.save(run_dir)
        flagged = [c.path for c in change.checks if c.status in review.FLAGGED]
        print(
            f"  {src.key:38} ${change.cost_usd:.4f} verified {change.verified_ratio:5.0%}"
            + (f"  flagged: {', '.join(flagged)}" if flagged else "")
        )
    print(f"\nrun saved to {run_dir}; total spent ${ledger.total_usd():.4f}")


REVIEWS_DIR = CACHE_DIR / "reviews"


def cmd_review(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args)
    done = review.load_reviews(REVIEWS_DIR)
    # Reviews are keyed by card, so only main pages are reviewed here; campaign variants are
    # shown alongside in `scout report` and merged at publish.
    changes = list(_load_run(run_dir)[0].values())
    pending = [
        c
        for c in changes
        if (not args.only or c["card_id"] in args.only)
        and done.get(c["card_id"], {}).get("content_hash") != c["content_hash"]
    ]
    # Flagged cards first, while attention is fresh; fully verified ones are quick approvals.
    pending.sort(
        key=lambda c: (-sum(ch["status"] in review.FLAGGED for ch in c["checks"]), c["card_id"])
    )
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


def _load_run(run_dir) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """(main-page changes by card, campaign-variant changes by card) from a run folder."""
    main: dict[str, dict] = {}
    variants: dict[str, list[dict]] = defaultdict(list)
    for p in sorted(run_dir.glob("*.json")):
        if p.name.endswith(".invalid.json"):
            continue
        c = json.loads(p.read_text())
        if "/variants/" in c.get("source_key", ""):
            variants[c["card_id"]].append(c)
        else:
            main[c["card_id"]] = c
    return main, dict(variants)


def _run_dir(args: argparse.Namespace):
    return CACHE_DIR / "runs" / args.run if args.run else review.latest_run(CACHE_DIR / "runs")


def cmd_revalidate(args: argparse.Namespace) -> None:
    """Re-check a run against the current schema and evidence rules, for $0: invalid raw outputs
    are re-validated, and valid ones get their quote checks recomputed."""
    run_dir = _run_dir(args)
    seeds = {c.id: c for c in load_seed()}
    for path in sorted(run_dir.glob("*.json")):
        if path.name.endswith(".invalid.json"):
            continue
        change = json.loads(path.read_text())
        hit = load_cached(change.get("source_key") or change["card_id"], CACHE_DIR)
        if hit:
            card = ExtractedCard.model_validate(change["extracted"])
            change["checks"] = [asdict(c) for c in check_card(card, hit[1])]
            path.write_text(json.dumps(change, indent=2))
    ledger = Ledger(CACHE_DIR / "spend.jsonl").entries()
    for path in sorted(run_dir.glob("*.invalid.json")):
        card_id = path.name.removesuffix(".invalid.json")
        saved = json.loads(path.read_text())
        # Older invalid files lack usage; the spend ledger recorded it when the call was made.
        paid = [e for e in ledger if e["card_id"] == card_id]
        usage = saved.get("usage") or {
            "inputTokens": paid[-1]["input_tokens"] if paid else 0,
            "outputTokens": paid[-1]["output_tokens"] if paid else 0,
        }
        meta, page = load_cached(card_id, CACHE_DIR)
        try:
            change = to_change(
                seeds[card_id],
                saved["raw"],
                page_text=page,
                content_hash=meta["content_hash"],
                model_id=saved.get("model_id") or (paid[-1]["model_id"] if paid else ""),
                usage=usage,
                cost=saved.get("cost_usd") or (paid[-1]["cost_usd"] if paid else 0.0),
            )
        except InvalidExtraction as e:
            print(f"  {card_id:38} still invalid: {e}")
            continue
        change.save(run_dir)
        path.unlink()
        print(f"  {card_id:38} recovered, verified {change.verified_ratio:.0%}")


def cmd_report(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args)
    pages = {}
    for p in run_dir.glob("*.json"):
        cid = p.name.removesuffix(".invalid.json").removesuffix(".json")
        hit = load_cached(cid, CACHE_DIR)
        if hit:
            pages[cid] = hit[1]
    out = CACHE_DIR / "report.html"
    out.write_text(report.build(run_dir, pages))
    print(f"wrote {out}  (open it: open {out})")


PREVIEW_PATH = CACHE_DIR / "preview_snapshot.json"


def cmd_preview(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args)
    changes, variants = _load_run(run_dir)
    snapshot = publish.build_preview(load_seed(), changes, variants)
    cards, notes = overrides.apply(snapshot.cards, overrides.load())
    snapshot = snapshot.model_copy(update={"cards": cards})
    print("\n".join(f"  {n}" for n in notes))
    PREVIEW_PATH.write_text(snapshot.model_dump_json(indent=2) + "\n")
    print(f"wrote {PREVIEW_PATH} ({len(snapshot.cards)} cards, UNREVIEWED preview)")


def cmd_compare(args: argparse.Namespace) -> None:
    """Baseline snapshot (default: the preview, i.e. the model it was built from) vs a run."""
    run_dir = _run_dir(args)
    changes, variants = _load_run(run_dir)
    other = publish.build_preview(load_seed(), changes, variants)
    baseline = CatalogSnapshot.model_validate_json((CACHE_DIR / args.baseline).read_text())
    rep = compare.compare(baseline, other)
    model = next(iter(changes.values()))["model_id"] if changes else "?"
    print(f"baseline {args.baseline}  vs  run {run_dir.name} ({model})")
    print(
        f"{rep.compared} cards compared, {rep.fields_total} fields: "
        f"{rep.fields_total - len(rep.diffs)} agree, {len(rep.diffs)} differ "
        f"({rep.agreement:.1%} agreement)"
    )
    if rep.only_in_a or rep.only_in_b:
        print(f"only in baseline: {rep.only_in_a}\nonly in run: {rep.only_in_b}")
    by_field: dict[str, int] = {}
    for d in rep.diffs:
        by_field[d.field] = by_field.get(d.field, 0) + 1
    print("differences by field:", dict(sorted(by_field.items(), key=lambda kv: -kv[1])))
    for d in rep.diffs:
        print(f"  {d.card_id:34} {d.field:28} baseline={d.a!r}\n  {'':34} {'':28} run     ={d.b!r}")
    out = CACHE_DIR / f"compare-{run_dir.name}.json"
    out.write_text(json.dumps([d.__dict__ for d in rep.diffs], indent=2, default=str))
    print(f"\nsaved {out}")


def cmd_stats(args: argparse.Namespace) -> None:
    s = review.accuracy(review.load_reviews(REVIEWS_DIR))
    print(
        f"\n{s['cards_approved']} approved, {s['cards_rejected']} rejected; "
        f"{s['fields_reviewed']} fields reviewed, {s['fields_edited']} edited "
        f"→ {s['accepted_unchanged']:.1%} accepted unchanged"
    )


def _reviews_dir(args: argparse.Namespace):
    return CACHE_DIR / args.reviews if getattr(args, "reviews", None) else REVIEWS_DIR


def cmd_publish(args: argparse.Namespace) -> None:
    if args.from_latest:
        version, latest = publish.latest()
        if latest is None:
            raise SystemExit("nothing published yet")
        print(f"  starting from v{version}")
        cards = latest.cards
        if args.update_from_run:
            changes, variants = _load_run(CACHE_DIR / "runs" / args.update_from_run)
            cards, notes = publish.update_from_run(cards, load_seed(), changes, variants)
            print("\n".join(f"  {n}" for n in notes))
    elif args.from_preview:
        if not args.verification:
            raise SystemExit("--from-preview needs --verification <dir under catalog/.cache>")
        preview = CatalogSnapshot.model_validate_json(PREVIEW_PATH.read_text())
        cards, notes = publish.promote_preview(
            preview, publish.load_verification(CACHE_DIR / args.verification)
        )
        print("\n".join(f"  {n}" for n in notes))
    else:
        reviews_dir = _reviews_dir(args)
        if not reviews_dir.exists():
            raise SystemExit(f"no reviews at {reviews_dir}")
        cards = publish.build(load_seed(), review.load_reviews(reviews_dir))
    # Fetch-time findings (HTML vs rendered divergence) from each card's latest fetch.
    metas = {c.id: load_cached(c.id, CACHE_DIR) for c in cards}
    cards, notes = publish.mark_page_variants(
        cards, {cid: hit[0].get("variant") for cid, hit in metas.items() if hit}
    )
    print("\n".join(f"  {n}" for n in notes))
    # Human corrections win over any extraction, on every publish path.
    cards, notes = overrides.apply(cards, overrides.load())
    print("\n".join(f"  {n}" for n in notes))
    path = publish.publish(cards)
    open_cards = sum(c.availability == "open" for c in cards)
    if path is None:
        print(f"catalog unchanged ({len(cards)} cards); no new snapshot written")
    else:
        print(
            f"wrote {path.relative_to(publish.REPO_ROOT)}: {open_cards} open + "
            f"{len(cards) - open_cards} closed cards"
        )


def cmd_release(args: argparse.Namespace) -> None:
    bucket = args.bucket or os.environ.get("CATALOG_BUCKET")
    if not bucket:
        raise SystemExit("--bucket (or CATALOG_BUCKET) is required")
    import boto3

    s3 = boto3.client("s3")
    try:
        plan, body = release.plan(s3, bucket, args.prefix, args.version, rollback=args.rollback)
    except release.ReleaseError as e:
        raise SystemExit(f"release refused: {e}") from None
    upload = (
        f"upload {plan.snapshot_key} ({len(body):,} bytes)"
        if plan.upload
        else (f"{plan.snapshot_key} already on S3 (identical)")
    )
    print(f"  {upload}\n  LATEST: {plan.previous or '(none)'} -> {plan.version}")
    if not args.live:
        print("dry run: nothing written (add --live)")
        return
    try:
        release.apply(s3, bucket, plan, body)
    except release.ReleaseError as e:
        raise SystemExit(f"release refused: {e}") from None
    print(f"released v{plan.version} to s3://{bucket}/{args.prefix}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="scout")
    sub = parser.add_subparsers(required=True)

    fetch = sub.add_parser("fetch", help="fetch Issuer pages into the local cache ($0)")
    fetch.add_argument("--priority", default="P0", choices=["P0", "P1"])
    fetch.add_argument("--only", type=lambda s: s.split(","), help="comma-separated card ids")
    fetch.add_argument("--no-browser", action="store_true", help="HTTP only, skip rendering")
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

    rv = sub.add_parser("revalidate", help="re-check saved invalid outputs vs current schema ($0)")
    rv.add_argument("--run", help="run id (default: latest)")
    rv.set_defaults(func=cmd_revalidate)

    rp = sub.add_parser("report", help="HTML overview of a run to skim before reviewing ($0)")
    rp.add_argument("--run", help="run id (default: latest)")
    rp.set_defaults(func=cmd_report)

    pv = sub.add_parser("preview", help="local demo snapshot from an unreviewed run ($0)")
    pv.add_argument("--run", help="run id (default: latest)")
    pv.set_defaults(func=cmd_preview)

    cp = sub.add_parser("compare", help="field agreement: a snapshot vs another model's run ($0)")
    cp.add_argument("--run", help="run id (default: latest)")
    cp.add_argument(
        "--baseline", default="preview_snapshot.json", help="snapshot under catalog/.cache"
    )
    cp.set_defaults(func=cmd_compare)

    sub.add_parser("stats", help="extraction accuracy from reviews").set_defaults(func=cmd_stats)
    pb = sub.add_parser("publish", help="write the next Catalog Snapshot")
    pb.add_argument("--reviews", help="reviews folder under catalog/.cache (default: reviews)")
    pb.add_argument("--from-preview", action="store_true", help="promote the preview snapshot")
    pb.add_argument(
        "--from-latest", action="store_true", help="republish the latest version (+ overrides)"
    )
    pb.add_argument(
        "--update-from-run",
        help="with --from-latest: replace cards re-extracted in this run (gated on evidence)",
    )
    pb.add_argument("--verification", help="field-verification folder under catalog/.cache")
    pb.set_defaults(func=cmd_publish)

    rl = sub.add_parser(
        "release", help="ship a snapshot to S3 and move LATEST (dry run unless --live)"
    )
    rl.add_argument("--version", help="MAJOR.MINOR (default: newest local snapshot)")
    rl.add_argument("--bucket", help="catalog bucket (default: $CATALOG_BUCKET)")
    rl.add_argument("--prefix", default="catalog/us/")
    rl.add_argument(
        "--rollback", action="store_true", help="allow pointing LATEST at an older version"
    )
    rl.add_argument("--live", action="store_true", help="actually write to S3")
    rl.set_defaults(func=cmd_release)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
