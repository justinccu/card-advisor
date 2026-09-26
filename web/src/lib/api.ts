"use client";

import { readSession } from "./session";
import type {
  ApplicantProfile,
  Evaluation,
  HeldCard,
  HeldCardIn,
  Velocity,
  Wallet,
  WalletAttestation,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  // Local demo identity. On AWS this becomes the Cognito access token (Authorization header);
  // the API ignores X-Dev-User outside APP_ENV=local.
  const devUser = readSession();
  if (devUser) headers.set("X-Dev-User", devUser);
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Can’t reach the API. Is it running? (make api)");
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
  putAttestation: (a: WalletAttestation) =>
    call<WalletAttestation>("/me/wallet/attestation", { method: "PUT", body: JSON.stringify(a) }),
  velocity: () => call<Velocity>("/me/velocity"),
  eligibility: (ids?: string[]) =>
    call<Evaluation[]>(
      `/me/eligibility${ids?.length ? `?${ids.map((i) => `card_id=${encodeURIComponent(i)}`).join("&")}` : ""}`,
    ),
  profile: () => call<ApplicantProfile>("/me/profile"),
  putProfile: (p: ApplicantProfile) =>
    call<ApplicantProfile>("/me/profile", { method: "PUT", body: JSON.stringify(p) }),
  deleteMe: () => call<void>("/me", { method: "DELETE" }),
};
