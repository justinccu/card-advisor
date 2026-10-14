"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUp, Maximize2, RotateCcw, Sparkles, Square, ThumbsDown, ThumbsUp } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  MAX_PROMPT_CHARS,
  TOOL_HINTS,
  linkedCardIds,
  sanitizeReply,
  type AdvisorCard,
  type ChatMessage,
} from "@/lib/advisor";
import { fee, offerHeadline } from "@/lib/format";
import { STAGGER, press, spring, tween, useCalm } from "@/lib/motion";
import { useReveal } from "@/lib/reveal";
import { api } from "@/lib/api";
import type { FeedbackReason, RuleFacts, TurnFeedback } from "@/lib/types";

import { useAdvisor } from "./AdvisorProvider";
import { CardArt } from "./CardArt";
import { useSession } from "./Providers";
import { RuleCitation } from "./RuleCitation";
import { SwapText } from "./SwapText";

const SUGGESTIONS = [
  "Which card fits my spending best?",
  "If I spent $800 a month on dining, what would you pick?",
  "Can I still get the Chase Sapphire Preferred welcome offer?",
];
const MAX_CARD_TILES = 3;

/** The Advisor conversation: in the floating panel (`panel`) or on the /advisor page. */
export function AdvisorChat({ panel = false }: { panel?: boolean }) {
  const { uid, ready } = useSession();
  const { available, messages, busy, quota, cards, send, stop, reset } = useAdvisor();
  const [draft, setDraft] = useState("");
  const log = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const stick = useRef(true); // follow the answer unless the reader scrolled up
  // Cited rules (rule:<id>) show their source; the rules change only with a deploy.
  const { data: rules } = useQuery({ queryKey: ["rules"], queryFn: api.rules, staleTime: Infinity });
  const md = useMemo(
    () => markdownComponents(cards, new Map((rules ?? []).map((r) => [r.rule_id, r]))),
    [cards, rules],
  );

  useEffect(() => {
    const el = log.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // An answer is revealed word by word after it arrives: keep following it as it grows.
  useEffect(() => {
    const el = log.current;
    if (!el) return;
    const follow = new MutationObserver(() => {
      if (stick.current) el.scrollTop = el.scrollHeight;
    });
    follow.observe(el, { childList: true, subtree: true, characterData: true });
    return () => follow.disconnect();
  }, [ready, available]);

  const outOfMessages = !!quota && quota.remaining <= 0;
  const submit = (text: string) => {
    if (!text.trim() || busy || outOfMessages) return;
    stick.current = true;
    send(text.slice(0, MAX_PROMPT_CHARS));
    setDraft("");
    if (input.current) input.current.style.height = "";
  };

  const height = panel ? "h-[min(640px,calc(88dvh-56px))]" : "h-[calc(100dvh-10rem)] min-h-[480px]";

  if (!available)
    return <Notice>The Advisor isn’t available on this site yet.</Notice>;
  if (!ready) return <div className={height} />;

  return (
    <div className={`flex flex-col ${height}`}>
      <header className={`flex items-center gap-2 pb-3 ${panel ? "pr-10" : ""}`}>
        <h2 className="text-[17px] font-semibold">Advisor</h2>
        {quota && (
          <span
            className="whitespace-nowrap rounded-full bg-tile px-2 py-0.5 text-[12px] text-ink-2"
            aria-live="polite"
            aria-atomic="true"
          >
            <SwapText text={String(quota.remaining)} />
            <span className="max-sm:hidden"> of {quota.limit}</span> {quota.guest ? "free left" : "left today"}
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          {messages.length > 0 && (
            <motion.button
              whileTap={press}
              transition={spring.micro}
              onClick={reset}
              aria-label="New conversation"
              className="flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[13px] text-link hover:bg-black/[0.04] dark:hover:bg-white/10"
            >
              <RotateCcw size={13} aria-hidden /> New<span className="max-sm:hidden"> conversation</span>
            </motion.button>
          )}
          {panel && (
            <Link
              href="/advisor/"
              aria-label="Open the Advisor page"
              className="grid size-8 place-items-center rounded-full text-ink-2 hover:bg-black/[0.04] dark:hover:bg-white/10"
            >
              <Maximize2 size={15} aria-hidden />
            </Link>
          )}
        </div>
      </header>

      <div
        ref={log}
        role="log"
        aria-label="Conversation with the Advisor"
        aria-busy={busy}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
        className="-mx-2 flex-1 space-y-4 overflow-y-auto overscroll-contain px-2 pb-2"
      >
        {messages.length === 0 ? (
          <div className="pt-6 text-center">
            <Sparkles className="mx-auto mb-3 text-action" size={26} aria-hidden />
            <p className="text-[15px] text-ink-2">
              Ask about cards for your spending, issuer rules like Chase 5/24, or building US credit.
            </p>
            {!uid && (
              <p className="mx-auto mt-2 max-w-[380px] text-[13px] text-ink-3">
                Try it free: 10 messages without an account.{" "}
                <Link href="/signin/" className="text-link underline">
                  Sign in
                </Link>{" "}
                to check issuer rules against your own cards.
              </p>
            )}
            <ul className="mt-5 flex flex-col items-center gap-2">
              {SUGGESTIONS.map((s) => (
                <li key={s}>
                  <motion.button
                    whileTap={press}
                    transition={spring.micro}
                    disabled={outOfMessages}
                    onClick={() => submit(s)}
                    className="rounded-full bg-tile px-4 py-2 text-[14px] hover:bg-black/[0.06] disabled:opacity-50 dark:hover:bg-white/10"
                  >
                    {s}
                  </motion.button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          messages.map((m) =>
            m.role === "user" ? (
              <p
                key={m.id}
                className="ml-auto w-fit max-w-[85%] whitespace-pre-wrap rounded-[20px] bg-action px-4 py-2 text-[15px] text-white"
              >
                {m.text}
              </p>
            ) : (
              <Reply key={m.id} message={m} cards={cards} components={md} />
            ),
          )
        )}
      </div>

      <form
        className="mt-2 flex items-end gap-2 rounded-[22px] bg-tile p-1.5 pl-4 ring-action/50 focus-within:ring-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit(draft);
        }}
      >
        <label htmlFor="advisor-input" className="sr-only">
          Message the Advisor
        </label>
        <textarea
          id="advisor-input"
          ref={input}
          rows={1}
          value={draft}
          maxLength={MAX_PROMPT_CHARS}
          disabled={outOfMessages}
          placeholder={
            outOfMessages
              ? quota!.resets_at
                ? `You’ve used today’s messages. More at ${resetTime(quota!.resets_at)}.`
                : "You’ve used the free messages. Sign in to keep going."
              : "Ask about cards, offers or eligibility"
          }
          onChange={(e) => {
            setDraft(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = `${Math.min(e.target.scrollHeight, 140)}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault(); // Enter sends; Shift+Enter or an IME's Enter adds a line
              submit(draft);
            }
          }}
          className="max-h-[140px] flex-1 resize-none bg-transparent py-1.5 text-[15px] outline-none placeholder:text-ink-3 focus-visible:outline-none disabled:cursor-not-allowed"
        />
        {/* One button that turns into Stop while answering; the icon swaps in place. */}
        <motion.button
          type={busy ? "button" : "submit"}
          whileTap={press}
          transition={spring.micro}
          onClick={busy ? stop : undefined}
          disabled={!busy && (!draft.trim() || outOfMessages)}
          aria-label={busy ? "Stop answering" : "Send"}
          className={`grid size-8 shrink-0 place-items-center rounded-full transition-colors duration-(--dur-fast) disabled:opacity-40 ${busy ? "bg-ink text-canvas" : "bg-action text-white"}`}
        >
          <AnimatePresence initial={false}>
            <IconSwap key={busy ? "stop" : "send"}>
              {busy ? <Square size={12} fill="currentColor" aria-hidden /> : <ArrowUp size={16} strokeWidth={2.5} aria-hidden />}
            </IconSwap>
          </AnimatePresence>
        </motion.button>
      </form>
      <p className="mt-2 text-center text-[12px] text-ink-3">
        {draft.length > MAX_PROMPT_CHARS - 200 ? (
          `${draft.length} / ${MAX_PROMPT_CHARS}`
        ) : !uid && outOfMessages ? (
          <>
            <Link href="/signin/" className="text-link underline">
              Sign in
            </Link>{" "}
            for 30 messages a day.
          </>
        ) : (
          "Figures come from our catalog and your profile. Not financial advice."
        )}
      </p>
    </div>
  );
}

function Reply({
  message: m,
  cards,
  components,
}: {
  message: ChatMessage;
  cards: Map<string, AdvisorCard>;
  components: Components;
}) {
  const calm = useCalm();
  // The checked answer arrives whole and is revealed word by word; what follows it (card rows,
  // rating) waits until the reveal ends.
  const { shown, revealing } = useReveal(m.text);
  const settled = m.done && !revealing;
  const linked = settled && !m.error ? linkedCardIds(m.text).filter((id) => cards.has(id)) : [];
  const status =
    (m.tool && TOOL_HINTS[m.tool]) ||
    (m.writing || m.text ? "Writing…" : m.rechecking ? "Double-checking the answer…" : "Thinking…");
  return (
    <div className="max-w-[92%] text-[15px] leading-relaxed">
      {/* An older agent that streamed could discard text for a retry: it fades out first. */}
      <AnimatePresence initial={false} mode="wait">
        {m.text && (
          <motion.div key={m.attempt ?? 0} exit={{ opacity: 0, filter: "blur(2px)", transition: tween.out }}>
            <Markdown
              remarkPlugins={[remarkGfm]}
              components={components}
              urlTransform={(url) => (url.startsWith("card:") || url.startsWith("rule:") ? url : "")}
              disallowedElements={["img"]}
              unwrapDisallowed
              skipHtml
            >
              {sanitizeReply(shown)}
            </Markdown>
          </motion.div>
        )}
      </AnimatePresence>
      {!m.done && !m.error && (
        <p className="mt-1 text-[13px]">
          <SwapText text={status} className="shimmer" />
        </p>
      )}
      {m.done && !m.error && !m.text && <p className="enter-rise text-[13px] text-ink-3">Stopped before answering.</p>}
      {m.error && (
        <p role="alert" className="enter-rise mt-1 rounded-2xl bg-bad/10 px-3 py-2 text-[14px] text-bad">
          {m.error.message}
          {(m.error.code === "auth" || m.error.code === "signin") && (
            <>
              {" "}
              <Link href="/signin/" className="underline">
                Sign in
              </Link>
            </>
          )}
        </p>
      )}
      {linked.length > 0 && (
        <ul className="mt-3 space-y-2" aria-label="Cards mentioned">
          {/* initial={false}: answers loaded from history don't replay this on every open. */}
          <AnimatePresence initial={false}>
            {linked.slice(0, MAX_CARD_TILES).map((id, i) => (
              <motion.li
                key={id}
                initial={{ opacity: 0, transform: "translateY(4px)" }}
                animate={{ opacity: 1, transform: "translateY(0px)" }}
                transition={calm({ ...tween.in, delay: i * STAGGER })}
              >
                <CardRow card={cards.get(id)!} />
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
      {settled && !m.error && m.turnId && <Feedback message={m} />}
    </div>
  );
}

const REASONS: { value: FeedbackReason; label: string }[] = [
  { value: "wrong_info", label: "Wrong information" },
  { value: "not_what_i_asked", label: "Not what I asked" },
  { value: "missing_info", label: "Missing something" },
  { value: "other", label: "Other" },
];

/** 👍 / 👎 under an answer. Rating keeps that exchange (question, answer, the data the Advisor
 *  looked up) for 90 days to improve answers, and the control says so before anything is sent. */
function Feedback({ message: m }: { message: ChatMessage }) {
  const { rate } = useAdvisor();
  const [asking, setAsking] = useState(false); // the "what went wrong?" form after 👎
  const [reason, setReason] = useState<FeedbackReason | null>(null);
  const [comment, setComment] = useState("");
  const status = m.feedback?.status;
  const send = (feedback: TurnFeedback) => {
    setAsking(false);
    rate(m.id, feedback);
  };

  if (status === "sent")
    return (
      <p className="enter-rise mt-2 text-[12px] text-ink-3" role="status">
        {m.feedback!.rating === "up" ? "Thanks for the feedback." : "Thanks. We’ll look into it."}
      </p>
    );
  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-1">
        <Thumb label="Helpful" pressed={m.feedback?.rating === "up"} disabled={status === "sending"} onClick={() => send({ rating: "up" })}>
          <ThumbsUp size={14} aria-hidden />
        </Thumb>
        <Thumb label="Not helpful" pressed={asking || m.feedback?.rating === "down"} disabled={status === "sending"} onClick={() => setAsking((a) => !a)}>
          <ThumbsDown size={14} aria-hidden />
        </Thumb>
        <span className="ml-1 text-[11px] text-ink-3">Rating shares this exchange with us for 90 days to improve answers.</span>
      </div>
      {status === "error" && <p className="enter-rise mt-1 text-[12px] text-bad">Couldn’t send that. Try again.</p>}
      <AnimatePresence initial={false}>
        {asking && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1, transition: tween.reveal }}
            exit={{ height: 0, opacity: 0, transition: tween.out }}
            className="overflow-hidden"
          >
            <div className="mt-2 rounded-2xl bg-tile p-3">
              <p className="text-[13px] font-medium">What went wrong?</p>
              <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label="Reason">
                {REASONS.map((r) => (
                  <button
                    key={r.value}
                    type="button"
                    aria-pressed={reason === r.value}
                    onClick={() => setReason(r.value)}
                    className={`rounded-full px-3 py-1 text-[13px] ${reason === r.value ? "bg-action text-white" : "bg-surface ring-1 ring-hairline hover:bg-black/[0.04] dark:hover:bg-white/10"}`}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
              <label className="sr-only" htmlFor={`${m.id}-comment`}>
                Anything else
              </label>
              <textarea
                id={`${m.id}-comment`}
                rows={2}
                maxLength={500}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Anything else? (optional)"
                className="mt-2 w-full resize-none rounded-xl bg-surface px-3 py-2 text-[14px] outline-none ring-1 ring-hairline focus:ring-2 focus:ring-action"
              />
              <button
                type="button"
                disabled={!reason}
                onClick={() => send({ rating: "down", reason: reason!, comment: comment.trim() || undefined })}
                className="mt-2 rounded-full bg-action px-4 py-1.5 text-[13px] text-white disabled:opacity-40"
              >
                Send feedback
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Thumb({
  label,
  pressed,
  disabled,
  onClick,
  children,
}: {
  label: string;
  pressed: boolean;
  disabled: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <motion.button
      type="button"
      whileTap={press}
      transition={spring.micro}
      aria-label={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className={`grid size-7 place-items-center rounded-full transition-colors disabled:opacity-50 ${pressed ? "bg-action/15 text-action" : "text-ink-3 hover:bg-black/[0.05] hover:text-ink dark:hover:bg-white/10"}`}
    >
      {children}
    </motion.button>
  );
}

/** An icon replacing another in the same slot: scale and blur, both at once. */
function IconSwap({ children }: { children: React.ReactNode }) {
  const calm = useCalm();
  return (
    <motion.span
      initial={{ opacity: 0, transform: "scale(0.9)", filter: "blur(2px)" }}
      animate={{ opacity: 1, transform: "scale(1)", filter: "blur(0px)" }}
      exit={{ opacity: 0, transform: "scale(0.9)", filter: "blur(2px)" }}
      transition={calm({ duration: 0.2, ease: "easeInOut" })}
      className="grid place-items-center [grid-area:1/1]"
    >
      {children}
    </motion.span>
  );
}

function CardRow({ card }: { card: AdvisorCard }) {
  const open = card.availability === "open"; // a closed card gets no Apply button
  return (
    // overflow-hidden: the card art's drop shadow would otherwise be clipped by the scrolling log.
    <div className="flex items-center gap-3 overflow-hidden rounded-2xl bg-surface p-2.5 ring-1 ring-hairline">
      <CardArt cardId={card.id} issuerId={card.issuer_id} name={card.name} bare className="w-14 shrink-0" />
      <div className="min-w-0 flex-1">
        <Link href={`/cards/${card.id}/`} className="line-clamp-2 text-[14px] font-medium leading-snug hover:underline">
          {card.name}
        </Link>
        <p className="truncate text-[12px] text-ink-2">
          {open ? `${offerHeadline(card.offer)} · ${fee(card)}` : "No longer offered to new applicants"}
        </p>
      </div>
      {open && (
        <a
          href={card.url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 rounded-full bg-action px-3 py-1 text-[13px] text-white hover:bg-action-hover"
        >
          Apply
        </a>
      )}
    </div>
  );
}

/** Markdown elements styled for chat; links resolve only through the catalog (lib/advisor). */
function markdownComponents(cards: Map<string, AdvisorCard>, rules: Map<string, RuleFacts>): Components {
  const heading = ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-1 mt-3 font-semibold first:mt-0">{children}</p>
  );
  return {
    a: ({ href, children }) => {
      if (href?.startsWith("rule:")) {
        const rule = rules.get(href.slice(5));
        // An id no tool returned stays plain text: never a citation of a rule that doesn't exist.
        return rule ? <RuleCitation rule={rule}>{children}</RuleCitation> : <span>{children}</span>;
      }
      const card = href?.startsWith("card:") ? cards.get(href.slice(5)) : undefined;
      if (!card) return <span>{children}</span>;
      if (card.availability !== "open") {
        // Closed to new applicants: our page says so; the issuer's page would invite an application.
        return (
          <Link href={`/cards/${card.id}/`} className="text-link hover:underline">
            {children}
          </Link>
        );
      }
      return (
        <a href={card.url} target="_blank" rel="noopener noreferrer" className="text-link hover:underline">
          {children}
        </a>
      );
    },
    p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
    ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>,
    ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>,
    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
    h1: heading,
    h2: heading,
    h3: heading,
    h4: heading,
    code: ({ children }) => <code className="rounded bg-black/[0.05] px-1 text-[14px] dark:bg-white/10">{children}</code>,
    table: ({ children }) => (
      <div className="my-2 overflow-x-auto">
        <table className="w-full text-[14px]">{children}</table>
      </div>
    ),
    th: ({ children }) => <th className="border-b border-hairline px-2 py-1 text-left font-semibold">{children}</th>,
    td: ({ children }) => <td className="border-b border-hairline px-2 py-1 align-top">{children}</td>,
  };
}

function Notice({ children }: { children: React.ReactNode }) {
  return <div className="py-16 text-center text-[15px] text-ink-2">{children}</div>;
}

/** US Eastern midnight in the reader's own clock, e.g. "9:00 PM" in California. */
function resetTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
