import "server-only";

import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import type { CatalogCard, CatalogSnapshot } from "./types";

// Read once at build time: the static site is a pure function of one Catalog Snapshot.
let cached: CatalogSnapshot | null = null;

/** CATALOG_PATH if set; else the newest published snapshot (catalog/us/vMAJOR.MINOR.json, compared
 *  numerically so 1.10 beats 1.9); else the local unreviewed preview from `scout preview`. */
function resolveCatalogFile(): string {
  if (process.env.CATALOG_PATH) return path.resolve(process.cwd(), process.env.CATALOG_PATH);
  const dir = path.resolve(process.cwd(), "../catalog/us");
  const versions = existsSync(dir)
    ? readdirSync(dir)
        .map((f) => /^v(\d+)\.(\d+)\.json$/.exec(f))
        .filter((m): m is RegExpExecArray => !!m)
        .map((m) => [Number(m[1]), Number(m[2])] as const)
        .sort((a, b) => b[0] - a[0] || b[1] - a[1])
    : [];
  if (versions.length) return path.join(dir, `v${versions[0][0]}.${versions[0][1]}.json`);
  return path.resolve(process.cwd(), "../catalog/.cache/preview_snapshot.json");
}

export function getCatalog(): CatalogSnapshot {
  if (cached) return cached;
  cached = JSON.parse(readFileSync(resolveCatalogFile(), "utf8")) as CatalogSnapshot;
  return cached;
}

export function openCards(): CatalogCard[] {
  return getCatalog().cards.filter((c) => c.availability === "open");
}
