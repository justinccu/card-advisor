"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import {
  ADVISOR_URL,
  ask,
  loadConversation,
  newConversation,
  saveConversation,
  type AdvisorCard,
  type ChatMessage,
  type Conversation,
} from "@/lib/advisor";
import { api } from "@/lib/api";
import { GUEST_CONVERSATION, hasGuest } from "@/lib/guest";
import type { ChatQuota, TurnFeedback } from "@/lib/types";

import { useSession } from "./Providers";

// One conversation per device (ADR 0009), held above the pages so the floating panel and the
// /advisor page show the same chat, and closing the panel doesn't cut an answer off. A visitor
// who isn't signed in chats as a guest on the free trial (lib/guest), in a conversation of its own.

type Advisor = {
  /** false when this build has no Advisor to talk to */
  available: boolean;
  messages: ChatMessage[];
  busy: boolean;
  quota: ChatQuota | undefined;
  cards: Map<string, AdvisorCard>;
  send: (text: string) => void;
  /** 👍 / 👎 on an answer; the control says rating keeps that exchange 90 days */
  rate: (messageId: string, feedback: TurnFeedback) => void;
  stop: () => void;
  reset: () => void;
};

const AdvisorCtx = createContext<Advisor | null>(null);

const id = () => crypto.randomUUID();

export function AdvisorProvider({ cards, children }: { cards: AdvisorCard[]; children: React.ReactNode }) {
  const { uid } = useSession();
  const qc = useQueryClient();
  const [convo, setConvo] = useState<Conversation | null>(null);
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const byId = useMemo(() => new Map(cards.map((c) => [c.id, c])), [cards]);

  // Load this user's conversation, or the guest's; a different user never sees it.
  const owner = uid ?? GUEST_CONVERSATION;
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  if (owner !== loadedFor) {
    setLoadedFor(owner);
    setConvo(typeof window !== "undefined" ? loadConversation(owner) : null);
  }
  useEffect(() => () => abort.current?.abort(), [owner]);
  useEffect(() => {
    if (convo) saveConversation(owner, convo);
  }, [owner, convo]);

  const quotaKey = useMemo(() => ["chat-quota", owner], [owner]);
  const { data: quota } = useQuery({
    queryKey: quotaKey,
    queryFn: api.chatQuota,
    // A guest's quota is known once they have a guest session (their first message).
    enabled: !!ADVISOR_URL && (!!uid || hasGuest()),
  });

  const update = useCallback((msgId: string, change: (m: ChatMessage) => ChatMessage) => {
    setConvo((c) => c && { ...c, messages: c.messages.map((m) => (m.id === msgId ? change(m) : m)) });
  }, []);

  const send = useCallback(
    (raw: string) => {
      const text = raw.trim();
      if (!text || busy || !convo) return;
      const reply: ChatMessage = { id: id(), role: "assistant", text: "", tool: null, done: false };
      setConvo({ ...convo, messages: [...convo.messages, { id: id(), role: "user", text }, reply] });
      setBusy(true);
      const controller = new AbortController();
      abort.current = controller;
      (async () => {
        try {
          for await (const event of ask(text, convo.sessionId, controller.signal)) {
            if (event.type === "text") update(reply.id, (m) => ({ ...m, text: m.text + event.text, tool: null }));
            else if (event.type === "reset") update(reply.id, (m) => ({ ...m, text: "", tool: null }));
            else if (event.type === "done" && event.turn_id) {
              const turnId = event.turn_id;
              update(reply.id, (m) => ({ ...m, turnId }));
            }
            else if (event.type === "tool") update(reply.id, (m) => ({ ...m, tool: event.name }));
            else if (event.type === "quota")
              qc.setQueryData<ChatQuota>(quotaKey, {
                limit: event.limit,
                used: event.limit - event.remaining,
                remaining: event.remaining,
                resets_at: event.resets_at,
                guest: event.guest,
              });
            else if (event.type === "error") {
              // A guest's used-up trial is answered with a way to sign in.
              const code = event.code === "quota" && event.guest ? "signin" : event.code;
              update(reply.id, (m) => ({ ...m, error: { code, message: event.message } }));
              if (event.code === "quota") qc.invalidateQueries({ queryKey: quotaKey });
            }
          }
        } catch {
          /* stopped by the user: keep what arrived */
        } finally {
          update(reply.id, (m) => ({ ...m, done: true, tool: null }));
          setBusy(false);
          abort.current = null;
        }
      })();
    },
    [busy, convo, update, qc, quotaKey],
  );

  const rate = useCallback(
    (messageId: string, feedback: TurnFeedback) => {
      const turnId = convo?.messages.find((m) => m.id === messageId)?.turnId;
      if (!turnId) return;
      const mark = (status: "sending" | "sent" | "error") =>
        update(messageId, (m) => ({ ...m, feedback: { rating: feedback.rating, status } }));
      mark("sending");
      api.rateTurn(turnId, feedback).then(
        () => mark("sent"),
        () => mark("error"),
      );
    },
    [convo, update],
  );

  const stop = useCallback(() => abort.current?.abort(), []);
  const reset = useCallback(() => {
    abort.current?.abort();
    setConvo(newConversation()); // a new session id: the agent starts a fresh conversation
  }, []);

  const value = useMemo(
    () => ({
      available: !!ADVISOR_URL,
      messages: convo?.messages ?? [],
      busy,
      quota,
      cards: byId,
      send,
      rate,
      stop,
      reset,
    }),
    [convo, busy, quota, byId, send, rate, stop, reset],
  );
  return <AdvisorCtx.Provider value={value}>{children}</AdvisorCtx.Provider>;
}

export function useAdvisor(): Advisor {
  const ctx = useContext(AdvisorCtx);
  if (!ctx) throw new Error("useAdvisor outside AdvisorProvider");
  return ctx;
}
