"use client";

// The Advisor's free trial for visitors who aren't signed in (ADR 0009, temporary). The API
// makes a guest account (POST /guest) the first time a visitor sends a message; this browser
// keeps its tokens and renews the access token with Cognito's refresh-token flow, so the visitor
// stays the same guest with the same 10 messages. Guests can chat and rate answers, nothing else.
//  - dev (`make demo`): the API answers with a dev user id ("guest-..."), sent as X-Dev-User.
import { authHeaders } from "./auth";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POOL_ID = process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID;
const CLIENT_ID = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID;
const KEY = "card-advisor.guest";
/** The guest's conversation is stored under this name instead of a user id. */
export const GUEST_CONVERSATION = "guest";

type Guest = { devUser?: string; accessToken?: string; refreshToken?: string; expiresAt?: number };

/** No guest session can be had: the trial is paused, or this network started too many today. */
export class GuestUnavailable extends Error {}

function read(): Guest | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Guest) : null;
  } catch {
    return null;
  }
}

function write(guest: Guest | null): void {
  try {
    if (guest) window.localStorage.setItem(KEY, JSON.stringify(guest));
    else window.localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: the guest lasts for this page view */
  }
}

export function hasGuest(): boolean {
  return typeof window !== "undefined" && read() !== null;
}

/** After the runtime or API rejected the guest's token: the next message starts over. */
export function forgetGuest(): void {
  write(null);
}

async function start(): Promise<Guest> {
  let res: Response;
  try {
    res = await fetch(`${API}/guest`, { method: "POST" });
  } catch {
    throw new GuestUnavailable("Can’t reach the Advisor. Check your connection.");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new GuestUnavailable(body?.detail?.message ?? "Sign in to use the Advisor.");
  if (body.dev_user) return { devUser: body.dev_user };
  return {
    accessToken: body.access_token,
    refreshToken: body.refresh_token,
    expiresAt: Date.now() + body.expires_in * 1000,
  };
}

/** A new access token from Cognito's public endpoint (the site's CSP allows cognito-idp), or
 *  null once the refresh token has expired (30 days). */
async function refresh(guest: Guest): Promise<Guest | null> {
  const region = POOL_ID?.split("_")[0];
  let res: Response;
  try {
    res = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
      },
      body: JSON.stringify({
        AuthFlow: "REFRESH_TOKEN_AUTH",
        ClientId: CLIENT_ID,
        AuthParameters: { REFRESH_TOKEN: guest.refreshToken },
      }),
    });
  } catch {
    throw new GuestUnavailable("Can’t reach the Advisor. Check your connection.");
  }
  if (!res.ok) return null;
  const result = (await res.json()).AuthenticationResult;
  return { ...guest, accessToken: result.AccessToken, expiresAt: Date.now() + result.ExpiresIn * 1000 };
}

/** The guest's headers. `create` starts a guest when there is none (only to send a message);
 *  otherwise there may be none ({}). Throws GuestUnavailable when one can't be started. */
export async function guestHeaders(create: boolean): Promise<Record<string, string>> {
  let guest = read();
  if (guest?.refreshToken && (guest.expiresAt ?? 0) - 60_000 < Date.now()) {
    guest = await refresh(guest);
    write(guest);
  }
  if (!guest) {
    if (!create) return {};
    guest = await start();
    write(guest);
  }
  return guest.devUser ? { "X-Dev-User": guest.devUser } : { Authorization: `Bearer ${guest.accessToken}` };
}

/** Who talks to the Advisor: the signed-in user, else this browser's guest (if any yet). */
export async function advisorHeaders(): Promise<Record<string, string>> {
  const auth = await authHeaders();
  return Object.keys(auth).length ? auth : guestHeaders(false).catch(() => ({}));
}
