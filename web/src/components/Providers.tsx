"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import { createContext, useCallback, useContext, useMemo, useState, useSyncExternalStore } from "react";

import { SESSION_KEY, readSession, writeSession } from "@/lib/session";

// --- Session (local demo sign-in; Cognito on AWS) ---------------------------------------

type Session = { uid: string | null; ready: boolean; signIn: (uid: string) => void; signOut: () => void };
const SessionCtx = createContext<Session | null>(null);

// localStorage is the source of truth; subscribe to it instead of mirroring it into state.
function subscribe(onChange: () => void) {
  const onStorage = (e: StorageEvent) => e.key === SESSION_KEY && onChange();
  window.addEventListener("storage", onStorage); // other tabs
  window.addEventListener("card-advisor:session", onChange); // this tab
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener("card-advisor:session", onChange);
  };
}

// --- Compare selection ------------------------------------------------------------------

export const MAX_COMPARE = 3;
type Compare = { ids: string[]; toggle: (id: string) => void; clear: () => void };
const CompareCtx = createContext<Compare | null>(null);

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1 } } }),
  );
  // undefined on the server / before hydration -> not ready yet.
  const stored = useSyncExternalStore(subscribe, readSession, () => undefined);
  const uid = stored ?? null;
  const ready = stored !== undefined;
  const [ids, setIds] = useState<string[]>([]);

  const signIn = useCallback(
    (next: string) => {
      client.clear();
      writeSession(next);
    },
    [client],
  );
  const signOut = useCallback(() => {
    client.clear();
    writeSession(null);
  }, [client]);

  const toggle = useCallback((id: string) => {
    setIds((cur) =>
      cur.includes(id) ? cur.filter((x) => x !== id) : cur.length >= MAX_COMPARE ? cur : [...cur, id],
    );
  }, []);
  const clear = useCallback(() => setIds([]), []);

  const session = useMemo(() => ({ uid, ready, signIn, signOut }), [uid, ready, signIn, signOut]);
  const compare = useMemo(() => ({ ids, toggle, clear }), [ids, toggle, clear]);

  return (
    <QueryClientProvider client={client}>
      {/* Honors prefers-reduced-motion: transforms become instant, opacity fades remain. */}
      <MotionConfig reducedMotion="user">
        <SessionCtx.Provider value={session}>
          <CompareCtx.Provider value={compare}>{children}</CompareCtx.Provider>
        </SessionCtx.Provider>
      </MotionConfig>
    </QueryClientProvider>
  );
}

export function useSession(): Session {
  const ctx = useContext(SessionCtx);
  if (!ctx) throw new Error("useSession outside Providers");
  return ctx;
}

export function useCompare(): Compare {
  const ctx = useContext(CompareCtx);
  if (!ctx) throw new Error("useCompare outside Providers");
  return ctx;
}
