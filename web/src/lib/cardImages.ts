"use client";

// Issuer card art for the local demo only (public/card-art is gitignored and never deployed; see
// lib/cardStyle). Provenance for every file (source URL, fetch time) is in manifest.json; entries
// marked "pending" have a known problem (see their "issue") and show the simulated face instead.
// The manifest is fetched at runtime, and only in the demo, so no build ever bundles it.
import { useEffect, useState } from "react";

import { REAL_FACES_AVAILABLE } from "./cardStyle";

type Entry = { file: string; status?: string };
type Manifest = Record<string, Entry>;

let cache: Manifest | null = null;
let loading: Promise<Manifest> | null = null;

function loadManifest(): Promise<Manifest> {
  loading ??= fetch("/card-art/manifest.json")
    .then((r) => (r.ok ? (r.json() as Promise<Manifest>) : {}))
    .catch(() => ({}))
    .then((m) => (cache = m));
  return loading;
}

/** The card's art URL when `enabled` (the viewer chose "real" in the demo), else null. */
export function useCardImage(cardId: string | null | undefined, enabled: boolean): string | null {
  const [manifest, setManifest] = useState<Manifest | null>(cache);
  const want = REAL_FACES_AVAILABLE && enabled;
  useEffect(() => {
    if (want && !manifest) loadManifest().then(setManifest);
  }, [want, manifest]);
  const entry = want && cardId && manifest ? manifest[cardId] : undefined;
  return entry && entry.status !== "pending" ? `/card-art/${entry.file}` : null;
}
