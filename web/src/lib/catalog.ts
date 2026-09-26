import "server-only";

import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import type { CatalogCard, CatalogSnapshot } from "./types";

// Read once at build time: the static site is a pure function of one Catalog Snapshot.
let cached: CatalogSnapshot | null = null;

/** CATALOG_PATH if set; else the newest published snapshot (catalog/us/vN.json); else the local
 *  unreviewed preview from `scout preview`. */
function resolveCatalogFile(): string {
  if (process.env.CATALOG_PATH) return path.resolve(process.cwd(), process.env.CATALOG_PATH);
  const dir = path.resolve(process.cwd(), "../catalog/us");
  const versions = existsSync(dir)
    ? readdirSync(dir)
        .map((f) => /^v(\d+)\.json$/.exec(f)?.[1])
        .filter((v): v is string => !!v)
        .map(Number)
        .sort((a, b) => b - a)
    : [];
  if (versions.length) return path.join(dir, `v${versions[0]}.json`);
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
