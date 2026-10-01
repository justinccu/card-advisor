"use client";

import { AUTH_MODE, authHeaders, signOut } from "./auth";
import { advisorHeaders } from "./guest";
import type {
  ApplicantProfile,
  ChatQuota,
  RuleFacts,
  EligibilityResult,
  HeldCard,
  HeldCardIn,
  HeldCardPatch,
  TurnFeedback,
  Velocity,
  Wallet,
  WalletAttestation,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// The catalog version this site was built from. Pinning it makes the API evaluate exactly the
// cards the page shows, even while a newer version is being rolled out (card_api.catalog).
// Unset for the unreviewed local preview, which the API serves as "latest".
let pinnedCatalogVersion: string | null = null;

export function pinCatalogVersion(version: string | null): void {
  pinnedCatalogVersion = version;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  // X-Dev-User locally; the Cognito access token otherwise (the API ignores X-Dev-User on AWS).
  for (const [k, v] of Object.entries(await authHeaders())) headers.set(k, v);
  let res: Response;
  try {
    // Plain concatenation keeps any path in BASE (e.g. an API stage prefix).
    const pin = pinnedCatalogVersion
      ? `${path.includes("?") ? "&" : "?"}catalog_version=${encodeURIComponent(pinnedCatalogVersion)}`
      : "";
    res = await fetch(`${BASE}${path}${pin}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Can’t reach the API. Is it running? (make api)");
  }
  if (res.status === 401 && AUTH_MODE === "cognito") {
    // Expired or revoked session: sign out so every page shows the signed-out state.
    await signOut();
    throw new ApiError(401, "Your session has ended. Sign in again.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  signup: (invite_code: string) =>
    call<{ user_id: string }>("/dev/signup", { method: "POST", body: JSON.stringify({ invite_code }) }),
  wallet: () => call<Wallet>("/me/wallet"),
  addCard: (card: HeldCardIn) =>
    call<HeldCard>("/me/wallet/cards", { method: "POST", body: JSON.stringify(card) }),
  removeCard: (id: string) => call<void>(`/me/wallet/cards/${id}`, { method: "DELETE" }),
  updateCard: (id: string, patch: HeldCardPatch) =>
    call<HeldCard>(`/me/wallet/cards/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  putAttestation: (a: WalletAttestation) =>
    call<WalletAttestation>("/me/wallet/attestation", { method: "PUT", body: JSON.stringify(a) }),
  velocity: () => call<Velocity>("/me/velocity"),
  eligibility: (ids?: string[]) =>
    call<EligibilityResult>(
      `/me/eligibility${ids?.length ? `?${ids.map((i) => `card_id=${encodeURIComponent(i)}`).join("&")}` : ""}`,
    ).then((r) => r.evaluations),
  profile: () => call<ApplicantProfile>("/me/profile"),
  putProfile: (p: ApplicantProfile) =>
    call<ApplicantProfile>("/me/profile", { method: "PUT", body: JSON.stringify(p) }),
  deleteMe: () => call<void>("/me", { method: "DELETE" }),
  // The Advisor's calls work for a guest on the free trial too (lib/guest).
  chatQuota: async () => call<ChatQuota>("/me/chat/quota", { headers: await advisorHeaders() }),
  rules: () => call<{ rules: RuleFacts[] }>("/rules").then((r) => r.rules),
  rateTurn: async (turnId: string, feedback: TurnFeedback) =>
    call<void>(`/me/chat/turns/${encodeURIComponent(turnId)}/feedback`, {
      method: "PUT",
      body: JSON.stringify(feedback),
      headers: await advisorHeaders(),
    }),
};
