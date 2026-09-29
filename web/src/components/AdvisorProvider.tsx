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
import type { ChatQuota } from "@/lib/types";

import { useSession } from "./Providers";

// One conversation per device (ADR 0009), held above the pages so the floating panel and the
// /advisor page show the same chat, and closing the panel doesn't cut an answer off.

type Advisor = {
  /** false when this build has no Advisor to talk to */
  available: boolean;
  messages: ChatMessage[];
  busy: boolean;
  quota: ChatQuota | undefined;
  cards: Map<string, AdvisorCard>;
  send: (text: string) => void;
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

  // Load this user's conversation (none when signed out); a different user never sees it.
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  if ((uid ?? null) !== loadedFor) {
    setLoadedFor(uid ?? null);
    setConvo(uid && typeof window !== "undefined" ? loadConversation(uid) : null);
  }
  useEffect(() => () => abort.current?.abort(), [uid]);
  useEffect(() => {
    if (uid && convo) saveConversation(uid, convo);
  }, [uid, convo]);

  const quotaKey = useMemo(() => ["chat-quota", uid], [uid]);
  const { data: quota } = useQuery({
    queryKey: quotaKey,
    queryFn: api.chatQuota,
    enabled: !!uid && !!ADVISOR_URL,
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
            else if (event.type === "tool") update(reply.id, (m) => ({ ...m, tool: event.name }));
            else if (event.type === "quota")
              qc.setQueryData<ChatQuota>(quotaKey, {
                limit: event.limit,
                used: event.limit - event.remaining,
                remaining: event.remaining,
                resets_at: event.resets_at,
              });
            else if (event.type === "error") {
              update(reply.id, (m) => ({ ...m, error: { code: event.code, message: event.message } }));
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
      stop,
      reset,
    }),
    [convo, busy, quota, byId, send, stop, reset],
  );
  return <AdvisorCtx.Provider value={value}>{children}</AdvisorCtx.Provider>;
}

export function useAdvisor(): Advisor {
  const ctx = useContext(AdvisorCtx);
  if (!ctx) throw new Error("useAdvisor outside AdvisorProvider");
  return ctx;
}
