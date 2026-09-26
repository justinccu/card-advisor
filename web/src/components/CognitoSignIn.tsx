"use client";

import { AnimatePresence, motion, useAnimate } from "motion/react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { authErrorMessage, confirmSignUp, resendSignUpCode, signIn, signUp } from "@/lib/auth";
import { press, spring } from "@/lib/motion";

import { Segmented } from "./Segmented";

type Step = "signin" | "signup" | "confirm";

/**
 * Cognito sign-in and invite-only sign-up, in the site's own UI. Sign-up sends the invite code to
 * the pre sign-up trigger (it's checked before the account exists); Cognito then emails a code to
 * confirm the address, after which we sign straight in.
 */
export function CognitoSignIn() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [scope, animate] = useAnimate();

  const shake = () =>
    animate(scope.current, { x: [0, -10, 8, -6, 4, 0] }, { duration: 0.4, ease: "easeOut" });

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(authErrorMessage(err));
      shake();
    } finally {
      setBusy(false);
    }
  }

  const finish = async () => {
    if ((await signIn(email, password)) === "confirm-email") {
      setStep("confirm");
      return;
    }
    router.push("/wallet/");
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setNote(null);
    run(async () => {
      if (step === "signin") return finish();
      if (step === "signup") {
        if ((await signUp(email, password, invite)) === "confirm") setStep("confirm");
        else await finish();
        return;
      }
      await confirmSignUp(email, code);
      await finish();
    });
  };

  const title = { signin: "Welcome back.", signup: "Join with an invite.", confirm: "Check your email." }[step];
  const subtitle = {
    signin: "Sign in to see which cards you can get.",
    signup: "Card Advisor is invite-only while we’re in preview.",
    confirm: `We sent a 6-digit code to ${email}.`,
  }[step];
  const ready =
    step === "confirm"
      ? code.trim().length >= 6
      : email.includes("@") && password.length >= (step === "signup" ? 12 : 1) &&
        (step !== "signup" || invite.trim().length >= 4);

  return (
    <div className="mx-auto max-w-[440px] px-4 pt-20">
      <h1 className="headline text-center text-[40px] font-semibold">{title}</h1>
      <p className="mt-3 text-center text-[17px] text-ink-2">{subtitle}</p>

      {step !== "confirm" && (
        <div className="mt-8 flex justify-center">
          <Segmented<Step>
            label="Sign in or create an account"
            value={step}
            onChange={(s) => {
              setStep(s);
              setError(null);
            }}
            options={[
              { value: "signin", label: "Sign in" },
              { value: "signup", label: "Create account" },
            ]}
          />
        </div>
      )}

      <form ref={scope} onSubmit={submit} className="mt-8 space-y-3">
        <AnimatePresence initial={false} mode="popLayout">
          {step === "confirm" ? (
            <motion.div key="confirm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <Input label="Verification code" value={code} onChange={setCode} inputMode="numeric" autoComplete="one-time-code" center />
            </motion.div>
          ) : (
            <motion.div key="form" className="space-y-3" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <Input label="Email" type="email" value={email} onChange={setEmail} autoComplete="email" />
              <Input
                label="Password"
                type="password"
                value={password}
                onChange={setPassword}
                autoComplete={step === "signup" ? "new-password" : "current-password"}
              />
              {step === "signup" && (
                <>
                  <p className="px-1 text-[12px] text-ink-3">
                    12+ characters with upper- and lowercase letters and a number.
                  </p>
                  <Input label="Invite code" value={invite} onChange={(v) => setInvite(v.toUpperCase())} autoComplete="off" center />
                </>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {error && (
          <p role="alert" className="text-center text-[13px] text-bad">
            {error}
          </p>
        )}
        {note && <p className="text-center text-[13px] text-ok">{note}</p>}

        <motion.button
          whileTap={press}
          transition={spring.micro}
          disabled={busy || !ready}
          className="w-full rounded-2xl bg-action py-3.5 text-[17px] font-medium text-white transition-opacity hover:bg-action-hover disabled:opacity-40"
        >
          {busy ? "One moment…" : { signin: "Sign in", signup: "Create account", confirm: "Confirm" }[step]}
        </motion.button>
      </form>

      {step === "confirm" && (
        <p className="mt-6 text-center text-[15px] text-ink-2">
          No email?{" "}
          <button
            type="button"
            className="text-link hover:underline"
            onClick={() => run(async () => {
              await resendSignUpCode(email);
              setNote("Sent a new code.");
            })}
          >
            Send a new code
          </button>
        </p>
      )}
    </div>
  );
}

function Input({
  label,
  value,
  onChange,
  type = "text",
  center = false,
  ...rest
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  center?: boolean;
  autoComplete?: string;
  inputMode?: "numeric" | "text" | "email";
}) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      type={type}
      placeholder={label}
      aria-label={label}
      spellCheck={false}
      className={`w-full rounded-2xl border border-hairline bg-surface px-4 py-3.5 text-[17px] outline-none focus:border-action focus:ring-4 focus:ring-action/20 ${center ? "text-center tracking-[0.15em]" : ""}`}
      {...rest}
    />
  );
}
