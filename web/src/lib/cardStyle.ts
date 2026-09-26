"use client";

// Which card faces to show: the simulated faces (lib/cardFaces, the default) or the issuer's card
// art ("real"). The card art is local-only (gitignored, never deployed), so "real" exists only in
// `make demo`, which builds with NEXT_PUBLIC_CARD_ART=1; everywhere else the site is simulated-only.
// In the demo the choice is a per-viewer preference kept in localStorage.
import { useSyncExternalStore } from "react";

export type CardStyle = "real" | "simulated";

/** Inlined at build time: true only in `make demo`. */
export const REAL_FACES_AVAILABLE = process.env.NEXT_PUBLIC_CARD_ART === "1";

const KEY = "card-advisor.card-style";
const EVENT = "card-advisor:card-style";
let fallback: CardStyle | null = null; // used only when storage is unavailable

function read(): CardStyle {
  if (!REAL_FACES_AVAILABLE) return "simulated";
  try {
    return window.localStorage.getItem(KEY) === "real" ? "real" : "simulated";
  } catch {
    return "simulated";
  }
}

export function setCardStyle(style: CardStyle): void {
  try {
    window.localStorage.setItem(KEY, style);
  } catch {
    /* storage unavailable: the choice lasts until the next page load */
    fallback = style;
  }
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function useCardStyle(): CardStyle {
  return useSyncExternalStore(
    subscribe,
    () => (REAL_FACES_AVAILABLE && fallback) || read(),
    () => "simulated",
  );
}
