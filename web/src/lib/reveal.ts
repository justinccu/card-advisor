"use client";

import { useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";

const WORD = /[A-Za-z0-9]/;

/** The first point at or after `n` where the Markdown so far renders cleanly: past the end of
 *  an English word (CJK text cuts between any two characters), a bold or code span, a link, or a
 *  table row. Cutting anywhere else flashes raw `**`, a half link `[Apply](card:...`, or a row
 *  of pipes until the rest arrives. */
export function revealCut(text: string, n: number): number {
  let cut = Math.min(n, text.length);
  for (let guard = 0; guard < 8 && cut < text.length; guard++) {
    const before = cut;
    while (cut < text.length && WORD.test(text[cut]) && WORD.test(text[cut - 1] ?? "")) cut++;
    while (text[cut] === "*" && text[cut - 1] === "*") cut++; // not between a pair of asterisks
    const head = text.slice(0, cut);
    if ((head.match(/\*\*/g) ?? []).length % 2) cut = after(text, "**", cut);
    else if ((head.match(/`/g) ?? []).length % 2) cut = after(text, "`", cut);
    else if (head.lastIndexOf("[") > head.lastIndexOf("]")) cut = after(text, "]", cut);
    else if (head.lastIndexOf("](") > head.lastIndexOf(")")) cut = after(text, ")", cut);
    else if (text.slice(head.lastIndexOf("\n") + 1).startsWith("|")) cut = after(text, "\n", cut);
    if (cut === before) break;
  }
  // "[label]" with the "(target)" still to come is a link, not text: take the target too.
  if (text[cut - 1] === "]" && text[cut] === "(") cut = after(text, ")", cut);
  return Math.min(cut, text.length);
}

function after(text: string, token: string, from: number): number {
  const i = text.indexOf(token, from);
  return i < 0 ? text.length : i + token.length;
}

/** Text that arrives while this is mounted is revealed word by word in about 1.5 seconds at most
 *  (the agent sends an answer only once it's checked, so this is presentation, never a draft).
 *  Text already there when it mounts, from history, shows at once; so does everything with
 *  reduced motion. */
export function useReveal(text: string): { shown: string; revealing: boolean } {
  const reduce = useReducedMotion();
  const [count, setCount] = useState(text.length);
  const done = useRef(text.length);

  useEffect(() => {
    done.current = Math.min(done.current, text.length); // an answer redone starts over
    if (reduce || done.current >= text.length) return;
    // Paced by time, not characters per frame (cuts snap to word and link ends, which would
    // otherwise rush it): ~8ms a character, between 0.6s and 1.5s.
    const from = done.current;
    const duration = Math.min(1500, Math.max(600, (text.length - from) * 8));
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const target = from + Math.ceil((text.length - from) * Math.min(1, (now - start) / duration));
      done.current = Math.max(done.current, revealCut(text, target));
      setCount(done.current);
      if (done.current < text.length) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [text, reduce]);

  if (reduce) return { shown: text, revealing: false };
  const n = Math.min(count, text.length);
  return { shown: text.slice(0, n), revealing: n < text.length };
}
