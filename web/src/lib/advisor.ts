"use client";

// The Advisor chat (ADR 0009). The browser calls the AgentCore Runtime directly with the user's
// Cognito access token; the runtime verifies it (CUSTOM_JWT), and the agent's tools call our API
// with that same token, so the Advisor can only see what the signed-in user can.
//  - dev (`make demo` + `make agent`): `agentcore dev` on :8080, as the demo's dev user.
//  - cognito: NEXT_PUBLIC_ADVISOR_URL, the runtime's invocations URL; unset hides the Advisor.
// A visitor who isn't signed in chats as a guest on the free trial (lib/guest).
import { AUTH_MODE, authHeaders } from "./auth";
import { GuestUnavailable, forgetGuest, guestHeaders } from "./guest";
import { ADVISOR_STORE_PREFIX } from "./session";
import type { CatalogCard } from "./types";

export const ADVISOR_URL: string | null =
  process.env.NEXT_PUBLIC_ADVISOR_URL ?? (AUTH_MODE === "dev" ? "http://localhost:8080/invocations" : null);

export const MAX_PROMPT_CHARS = 2000; // the agent rejects longer messages
const SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id";
// Only the local agent reads this (ADVISOR_LOCAL=1); the deployed runtime forwards only Authorization.
const DEV_USER_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Dev-User";

/** Just what the chat needs to turn `card:<id>` links into cards (passed down from the build). */
export type AdvisorCard = Pick<
  CatalogCard,
  "id" | "issuer_id" | "name" | "url" | "annual_fee_usd" | "first_year_annual_fee_usd" | "offer" | "availability"
>;

/** signin: the guest trial can't continue (used up, paused, or not available here) */
export type ErrorCode = "quota" | "auth" | "signin" | "input" | "internal" | "network";

export type AdvisorEvent =
  | { type: "quota"; limit: number; remaining: number; resets_at: string | null; guest?: boolean }
  | { type: "tool"; name: string }
  | { type: "text"; text: string }
  /** the answer so far is discarded (the agent retries after a malformed reply) */
  | { type: "reset" }
  | { type: "error"; code: ErrorCode; message: string; resets_at?: string | null; guest?: boolean }
  /** turn_id: the saved answer the user can rate (absent when it couldn't be saved) */
  | { type: "done"; turn_id?: string };

// --- streaming ----------------------------------------------------------------------------

function error(code: ErrorCode, message: string): AdvisorEvent {
  return { type: "error", code, message };
}

/** One SSE `data:` payload -> an event. The runtime's own failures arrive as {error, message}. */
export function toEvent(data: unknown): AdvisorEvent | null {
  if (!data || typeof data !== "object") return null;
  const d = data as Record<string, unknown>;
  if (typeof d.type === "string") return d as unknown as AdvisorEvent;
  if ("error" in d) return error("internal", "Something went wrong while answering. Please try again.");
  return null;
}

/** Splits an SSE byte stream into events; `rest` is an incomplete trailing block. */
export function parseSse(buffer: string): { events: AdvisorEvent[]; rest: string } {
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? "";
  const events: AdvisorEvent[] = [];
  for (const block of blocks) {
    const data = block
      .split(/\r?\n/)
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trimStart())
      .join("\n");
    if (!data) continue;
    try {
      const event = toEvent(JSON.parse(data));
      if (event) events.push(event);
    } catch {
      /* a malformed block: skip it rather than end the answer */
    }
  }
  return { events, rest };
}

/** Sends one message and yields the Advisor's events as they stream in. Always ends with a
 *  `done` or an `error` event (never throws, except when `signal` aborts). */
export async function* ask(prompt: string, sessionId: string, signal?: AbortSignal): AsyncGenerator<AdvisorEvent> {
  if (!ADVISOR_URL) {
    yield error("internal", "The Advisor isn’t available on this site yet.");
    return;
  }
  const headers: Record<string, string> = { "Content-Type": "application/json", [SESSION_HEADER]: sessionId };
  let identity = await authHeaders();
  const guest = !Object.keys(identity).length;
  if (guest) {
    try {
      identity = await guestHeaders(true);
    } catch (e) {
      yield error("signin", e instanceof GuestUnavailable ? e.message : "Sign in to use the Advisor.");
      return;
    }
  }
  for (const [k, v] of Object.entries(identity)) {
    headers[k === "X-Dev-User" ? DEV_USER_HEADER : k] = v;
  }
  let res: Response;
  try {
    res = await fetch(ADVISOR_URL, { method: "POST", headers, body: JSON.stringify({ prompt }), signal });
  } catch (e) {
    if (signal?.aborted) throw e;
    yield error(
      "network",
      AUTH_MODE === "dev" ? "Can’t reach the Advisor. Is it running? (make agent)" : "Can’t reach the Advisor. Check your connection.",
    );
    return;
  }
  if (res.status === 401 || res.status === 403) {
    if (guest) {
      forgetGuest(); // e.g. the trial account is gone: the next message starts a new one
      yield error("signin", "Your free trial session ended. Send your message again, or sign in.");
      return;
    }
    yield error("auth", "Your session has ended. Sign in again to keep chatting.");
    return;
  }
  if (res.status === 429) {
    yield error("internal", "The Advisor is busy right now. Try again in a moment.");
    return;
  }
  if (!res.ok || !res.body) {
    yield error("internal", `The Advisor couldn’t answer (HTTP ${res.status}). Please try again.`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const parsed = parseSse(done ? `${buffer}\n\n` : buffer);
    buffer = parsed.rest;
    for (const event of parsed.events) {
      yield event;
      if (event.type === "done" || event.type === "error") return;
    }
    if (done) break;
  }
  yield error("internal", "The answer was cut off. Please try again.");
}

// --- links --------------------------------------------------------------------------------

const MD_LINK = /\[([^\]]*)\]\(\s*<?([^)\s>]*)>?(?:\s+"[^"]*")?\s*\)/g;
const BARE_URL = /<?\b(?:https?:\/\/|www\.)[^\s<>)\]]+>?/gi;

/** The model may link only `card:<id>` (the site knows each card's official page) and cite
 *  `rule:<id>` (shown as the rule's source). Any other
 *  link keeps its label and loses its target; any bare URL in the text is removed. */
export function sanitizeReply(markdown: string): string {
  return markdown
    .replace(MD_LINK, (whole, label: string, href: string) =>
      href.startsWith("card:") || href.startsWith("rule:") ? whole : label,
    )
    .replace(BARE_URL, "[link removed]");
}

/** Card ids the reply links to, in order of first mention. */
export function linkedCardIds(markdown: string): string[] {
  const ids: string[] = [];
  for (const m of markdown.matchAll(/\]\(\s*card:([a-z0-9_]+)\s*\)/g)) {
    if (!ids.includes(m[1])) ids.push(m[1]);
  }
  return ids;
}

// --- this device's conversation -------------------------------------------------------------

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  /** assistant only: the tool running right now, for a progress hint */
  tool?: string | null;
  error?: { code: ErrorCode; message: string } | null;
  done?: boolean;
  /** assistant only: the saved answer's id, for 👍 / 👎 */
  turnId?: string;
  feedback?: { rating: "up" | "down"; status: "sending" | "sent" | "error" };
};

export type Conversation = { sessionId: string; messages: ChatMessage[]; updatedAt: number };

const MAX_STORED = 40;
// Raw turns stay in AgentCore Memory for 7 days; after that the agent no longer has them, so a
// quieter conversation starts over rather than showing history the Advisor can't see.
const IDLE_RESET_MS = 7 * 24 * 60 * 60 * 1000;

export function newConversation(): Conversation {
  return { sessionId: crypto.randomUUID(), messages: [], updatedAt: Date.now() };
}

export function loadConversation(uid: string): Conversation {
  try {
    const raw = window.localStorage.getItem(ADVISOR_STORE_PREFIX + uid);
    if (raw) {
      const c = JSON.parse(raw) as Conversation;
      if (c.sessionId && Array.isArray(c.messages) && Date.now() - c.updatedAt < IDLE_RESET_MS) {
        // An answer interrupted by a reload can't resume: keep what arrived.
        return { ...c, messages: c.messages.map((m) => (m.done === false ? { ...m, done: true, tool: null } : m)) };
      }
    }
  } catch {
    /* blocked or corrupt storage: start fresh */
  }
  return newConversation();
}

export function saveConversation(uid: string, c: Conversation): void {
  try {
    window.localStorage.setItem(
      ADVISOR_STORE_PREFIX + uid,
      JSON.stringify({ ...c, messages: c.messages.slice(-MAX_STORED), updatedAt: Date.now() }),
    );
  } catch {
    /* storage unavailable: the conversation lasts for this page view */
  }
}

export const TOOL_HINTS: Record<string, string> = {
  get_my_profile: "Reading your profile…",
  get_my_wallet: "Checking your wallet…",
  rank_cards: "Ranking cards for your spending…",
  check_eligibility: "Checking issuer rules…",
  get_card_details: "Looking up card details…",
};
