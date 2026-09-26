"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { pinCatalogVersion } from "@/lib/api";
import { AUTH_EVENT, SESSION_KEY, currentUserId, devSignIn, signOut as authSignOut } from "@/lib/auth";

// --- Session (dev sign-in locally; Cognito with `make web-aws` and on AWS) ----------------

type Session = {
  uid: string | null;
  /** false until we know whether someone is signed in (never on the server) */
  ready: boolean;
  /** dev mode only; Cognito sign-in happens on the sign-in page (lib/auth) */
  signIn: (uid: string) => void;
  signOut: () => Promise<void>;
};
const SessionCtx = createContext<Session | null>(null);

// Cognito keeps its tokens in localStorage under this prefix; a change in another tab (sign-in
// or sign-out there) must update this one too.
const COGNITO_STORAGE_PREFIX = "CognitoIdentityServiceProvider.";

// --- Compare selection ------------------------------------------------------------------

export const MAX_COMPARE = 3;
type Compare = { ids: string[]; toggle: (id: string) => void; clear: () => void };
const CompareCtx = createContext<Compare | null>(null);

export function Providers({
  children,
  catalogVersion,
}: {
  children: React.ReactNode;
  /** the snapshot this build rendered; null for the unreviewed preview */
  catalogVersion: string | null;
}) {
  pinCatalogVersion(catalogVersion);
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1 } } }),
  );
  const [{ uid, ready }, setUser] = useState<{ uid: string | null; ready: boolean }>({
    uid: null,
    ready: false,
  });
  const [ids, setIds] = useState<string[]>([]);

  useEffect(() => {
    let alive = true;
    const load = () =>
      currentUserId().then((next) => {
        if (!alive) return;
        setUser((cur) => {
          if (cur.ready && cur.uid !== next) client.clear(); // someone else's cached data
          return { uid: next, ready: true };
        });
      });
    const onStorage = (e: StorageEvent) => {
      if (!e.key || e.key === SESSION_KEY || e.key.startsWith(COGNITO_STORAGE_PREFIX)) load();
    };
    load();
    window.addEventListener(AUTH_EVENT, load); // this tab
    window.addEventListener("storage", onStorage); // other tabs
    return () => {
      alive = false;
      window.removeEventListener(AUTH_EVENT, load);
      window.removeEventListener("storage", onStorage);
    };
  }, [client]);

  const signIn = useCallback(
    (next: string) => {
      client.clear();
      devSignIn(next);
    },
    [client],
  );
  const signOut = useCallback(async () => {
    client.clear();
    await authSignOut();
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
