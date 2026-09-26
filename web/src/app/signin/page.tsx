"use client";

import { motion, useAnimate } from "motion/react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/Providers";
import { api, ApiError } from "@/lib/api";
import { press, spring } from "@/lib/motion";

const DEMO_USER = "demo-user";

/**
 * Local stand-in for Cognito's invite-only sign-up (the API's /dev/signup runs the same invite
 * redemption as the Cognito pre-sign-up trigger). On AWS this page becomes the Cognito
 * managed-login redirect with PKCE.
 */
export default function SignInPage() {
  const { signIn } = useSession();
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [scope, animate] = useAnimate();

  const shake = () =>
    animate(scope.current, { x: [0, -10, 8, -6, 4, 0] }, { duration: 0.4, ease: "easeOut" });

  async function redeem(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { user_id } = await api.signup(code);
      signIn(user_id);
      router.push("/wallet/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      shake();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-[440px] px-4 pt-20">
      <h1 className="headline text-center text-[40px] font-semibold">Join with an invite.</h1>
      <p className="mt-3 text-center text-[17px] text-ink-2">
        Card Advisor is invite-only while we&apos;re in preview.
      </p>
      <form ref={scope} onSubmit={redeem} className="mt-10 space-y-3">
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          placeholder="Invite code"
          aria-label="Invite code"
          autoComplete="off"
          spellCheck={false}
          className="w-full rounded-2xl border border-hairline bg-surface px-4 py-3.5 text-center text-[19px] tracking-[0.15em] outline-none focus:border-action focus:ring-4 focus:ring-action/20"
        />
        {error && (
          <p role="alert" className="text-center text-[13px] text-bad">
            {error}
          </p>
        )}
        <motion.button
          whileTap={press}
          transition={spring.micro}
          disabled={busy || code.length < 4}
          className="w-full rounded-2xl bg-action py-3.5 text-[17px] font-medium text-white transition-opacity hover:bg-action-hover disabled:opacity-40"
        >
          {busy ? "Checking…" : "Continue"}
        </motion.button>
      </form>
      <div className="mt-10 rounded-2xl bg-tile p-5 text-center">
        <p className="text-[15px] text-ink-2">Just looking? Try a demo account with five cards already in its wallet.</p>
        <button
          onClick={() => {
            signIn(DEMO_USER);
            router.push("/wallet/");
          }}
          className="mt-2 text-[15px] text-link hover:underline"
        >
          Use demo account ›
        </button>
        <p className="mt-3 text-[12px] text-ink-3">Local demo invite code: DEMO-2026</p>
      </div>
    </div>
  );
}
