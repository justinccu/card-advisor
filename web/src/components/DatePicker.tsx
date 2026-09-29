"use client";

import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useId, useRef, useState } from "react";

import { press, spring } from "@/lib/motion";

// A date field typed as MM/DD/YYYY, with an inline calendar that opens below it (inline rather
// than a popover, so it is never clipped by a sheet's scrolling area). Values are ISO dates
// ("2025-03-14") in the reader's local calendar.

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const pad = (n: number) => String(n).padStart(2, "0");

export function localIso(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export const todayIso = () => localIso(new Date());

/** "2025-03-14" -> "03/14/2025" */
export function isoToUs(iso: string): string {
  const [y, m, d] = iso.split("-");
  return `${m}/${d}/${y}`;
}

/** "03/14/2025" -> "2025-03-14"; null unless it is a real calendar date. */
export function usToIso(text: string): string | null {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(text.trim());
  if (!m) return null;
  const [mo, d, y] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const date = new Date(y, mo - 1, d);
  if (y < 1900 || date.getFullYear() !== y || date.getMonth() !== mo - 1 || date.getDate() !== d) return null;
  return localIso(date);
}

/** Typing aid: keeps digits, inserts the slashes, and pads a one-digit month or day when the
 *  reader types the slash themselves ("3/" -> "03/"). Re-applying it to its output is a no-op. */
export function maskUs(raw: string): string {
  const segs = ["", "", ""];
  const size = [2, 2, 4];
  let i = 0;
  let trailing = false;
  for (const ch of raw) {
    if (ch >= "0" && ch <= "9") {
      if (segs[i].length === size[i] && i < 2) i++;
      if (segs[i].length < size[i]) segs[i] += ch;
      trailing = false;
    } else if ("/-.".includes(ch) && i < 2 && segs[i]) {
      segs[i] = segs[i].padStart(2, "0");
      i++;
      trailing = true;
    }
  }
  return segs.slice(0, i + 1).filter((s, k) => s || k < i).join("/") + (trailing ? "/" : "");
}

function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return localIso(new Date(y, m - 1, d + days));
}

function longLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

export function DatePicker({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string;
  /** ISO date, or "" for none */
  value: string;
  /** called only with valid dates inside [min, max] */
  onChange: (iso: string) => void;
  min?: string;
  max?: string;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const grid = useRef<HTMLDivElement>(null);
  const [text, setText] = useState(value ? isoToUs(value) : "");
  const [open, setOpen] = useState(false);
  const [touched, setTouched] = useState(false);
  const anchor = value || (max && todayIso() > max ? max : todayIso());
  const [view, setView] = useState(() => ({ y: Number(anchor.slice(0, 4)), m: Number(anchor.slice(5, 7)) - 1 }));
  const [mode, setMode] = useState<"days" | "months">("days");
  const [focusDay, setFocusDay] = useState(anchor);
  const moveFocus = useRef(false);

  // A new value from outside (e.g. the calendar, or a reset) replaces what is typed.
  const [shown, setShown] = useState(value);
  if (value !== shown) {
    setShown(value);
    setText(value ? isoToUs(value) : "");
  }

  const iso = usToIso(text);
  const problem = !text
    ? "Enter a date as MM/DD/YYYY."
    : !iso
      ? "Enter a real date as MM/DD/YYYY."
      : max && iso > max
        ? `Choose a date on or before ${isoToUs(max)}.`
        : min && iso < min
          ? `Choose a date on or after ${isoToUs(min)}.`
          : null;

  // The form won't submit while the typed text isn't a usable date.
  useEffect(() => input.current?.setCustomValidity(problem ?? ""), [problem]);
  useEffect(() => {
    if (!moveFocus.current) return;
    moveFocus.current = false;
    grid.current?.querySelector<HTMLButtonElement>(`[data-day="${focusDay}"]`)?.focus();
  }, [focusDay, view]);

  const allowed = (day: string) => (!max || day <= max) && (!min || day >= min);

  const showMonthOf = (day: string) => setView({ y: Number(day.slice(0, 4)), m: Number(day.slice(5, 7)) - 1 });

  const openCalendar = () => {
    if (open) return;
    const start = iso && !problem ? iso : anchor;
    showMonthOf(start);
    setFocusDay(start);
    setMode("days");
    setOpen(true);
  };

  const pick = (day: string) => {
    setText(isoToUs(day));
    setTouched(true);
    onChange(day);
    setOpen(false);
    input.current?.focus();
  };

  const step = (months: number) =>
    setView(({ y, m }) => {
      const d = new Date(y, m + months, 1);
      return { y: d.getFullYear(), m: d.getMonth() };
    });

  const onGridKey = (e: React.KeyboardEvent) => {
    const moves: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    let next: string | null = null;
    if (e.key in moves) next = addDays(focusDay, moves[e.key]);
    else if (e.key === "PageUp" || e.key === "PageDown") {
      const [y, m, d] = focusDay.split("-").map(Number);
      const target = new Date(y, m - 1 + (e.key === "PageUp" ? -1 : 1), 1);
      const last = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
      next = localIso(new Date(target.getFullYear(), target.getMonth(), Math.min(d, last)));
    } else if (e.key === "Home") next = addDays(focusDay, -new Date(focusDay + "T00:00").getDay());
    else if (e.key === "End") next = addDays(focusDay, 6 - new Date(focusDay + "T00:00").getDay());
    if (!next) return;
    e.preventDefault();
    moveFocus.current = true;
    setFocusDay(next);
    showMonthOf(next);
  };

  const first = new Date(view.y, view.m, 1);
  const daysInMonth = new Date(view.y, view.m + 1, 0).getDate();
  const blanks = first.getDay();
  const today = todayIso();
  const monthStart = `${view.y}-${pad(view.m + 1)}-01`;
  const monthEnd = `${view.y}-${pad(view.m + 1)}-${pad(daysInMonth)}`;
  const canPrev = !min || monthStart > min;
  const canNext = !max || monthEnd < max;
  const showError = touched && !open && problem;

  return (
    <div
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation(); // close the calendar, not the sheet around it
          setOpen(false);
          input.current?.focus();
        }
      }}
    >
      <label htmlFor={id} className="text-[13px] text-ink-2">
        {label}
      </label>
      <div className="relative mt-1">
        <input
          ref={input}
          id={id}
          inputMode="numeric"
          autoComplete="off"
          placeholder="MM/DD/YYYY"
          value={text}
          aria-invalid={!!showError}
          aria-describedby={showError ? `${id}-error` : undefined}
          onClick={openCalendar}
          onChange={(e) => {
            const next = maskUs(e.target.value);
            setText(next);
            const parsed = usToIso(next);
            if (parsed && allowed(parsed)) {
              onChange(parsed);
              showMonthOf(parsed);
              setFocusDay(parsed);
            }
          }}
          onBlur={() => setTouched(true)}
          onInvalid={(e) => {
            e.preventDefault(); // show our message under the field, not the browser's bubble
            setTouched(true);
            setOpen(false);
            input.current?.focus();
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" && !open) {
              e.preventDefault();
              openCalendar();
            }
          }}
          className={`w-full rounded-xl bg-black/[0.05] py-2.5 pl-3 pr-11 text-[15px] tabular-nums outline-none focus:ring-2 dark:bg-white/10 ${showError ? "ring-2 ring-bad" : "focus:ring-action"}`}
        />
        <button
          type="button"
          onClick={() => (open ? setOpen(false) : openCalendar())}
          aria-label={open ? "Close calendar" : "Choose date from calendar"}
          aria-expanded={open}
          aria-controls={`${id}-calendar`}
          className={`absolute right-1.5 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-lg transition-colors ${open ? "bg-action text-white" : "text-ink-2 hover:bg-black/[0.06] dark:hover:bg-white/10"}`}
        >
          <CalendarDays size={17} aria-hidden />
        </button>
      </div>
      {showError && (
        <p id={`${id}-error`} className="mt-1 text-[13px] text-bad">
          {problem}
        </p>
      )}

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={`${id}-calendar`}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={spring.nav}
            className="overflow-hidden"
          >
            {/* padding inside the clipping box leaves room for the calendar's shadow */}
            <div className="px-2 pb-4 pt-2">
              <div className="mx-auto max-w-[340px] rounded-2xl bg-surface p-3 shadow-[var(--shadow)] ring-1 ring-hairline">
                <div className="flex items-center justify-between px-1 pb-2">
                  <button
                    type="button"
                    onClick={() => setMode(mode === "days" ? "months" : "days")}
                    aria-label={mode === "days" ? "Choose month and year" : "Back to days"}
                    className="flex items-center gap-1 rounded-lg px-2 py-1 text-[15px] font-semibold hover:bg-black/[0.05] dark:hover:bg-white/10"
                  >
                    {mode === "days" ? `${MONTHS[view.m]} ${view.y}` : view.y}
                    <ChevronRight
                      size={15}
                      className={`text-action transition-transform ${mode === "months" ? "rotate-90" : ""}`}
                      aria-hidden
                    />
                  </button>
                  <div className="flex items-center gap-1">
                    <NavButton
                      label={mode === "days" ? "Previous month" : "Previous year"}
                      disabled={mode === "days" ? !canPrev : !!min && view.y <= Number(min.slice(0, 4))}
                      onClick={() => (mode === "days" ? step(-1) : step(-12))}
                    >
                      <ChevronLeft size={18} />
                    </NavButton>
                    <NavButton
                      label={mode === "days" ? "Next month" : "Next year"}
                      disabled={mode === "days" ? !canNext : !!max && view.y >= Number(max.slice(0, 4))}
                      onClick={() => (mode === "days" ? step(1) : step(12))}
                    >
                      <ChevronRight size={18} />
                    </NavButton>
                  </div>
                </div>

                {mode === "months" ? (
                  <div className="grid grid-cols-3 gap-1.5 pb-1">
                    {MONTHS.map((name, m) => {
                      const start = `${view.y}-${pad(m + 1)}-01`;
                      const end = localIso(new Date(view.y, m + 1, 0));
                      const off = (!!max && start > max) || (!!min && end < min);
                      const current = value.slice(0, 7) === `${view.y}-${pad(m + 1)}`;
                      return (
                        <motion.button
                          key={name}
                          type="button"
                          whileTap={press}
                          transition={spring.micro}
                          disabled={off}
                          onClick={() => {
                            setView({ y: view.y, m });
                            setMode("days");
                          }}
                          className={`rounded-xl py-2.5 text-[14px] disabled:opacity-30 ${current ? "bg-action font-semibold text-white" : "hover:bg-black/[0.05] dark:hover:bg-white/10"}`}
                        >
                          {name.slice(0, 3)}
                        </motion.button>
                      );
                    })}
                  </div>
                ) : (
                  <>
                    <div className="grid grid-cols-7 pb-1 text-center text-[11px] font-medium uppercase text-ink-3" aria-hidden>
                      {WEEKDAYS.map((d) => (
                        <span key={d}>{d.slice(0, 1)}</span>
                      ))}
                    </div>
                    <div
                      ref={grid}
                      role="group"
                      aria-label={`${MONTHS[view.m]} ${view.y}`}
                      onKeyDown={onGridKey}
                      className="grid grid-cols-7 gap-y-0.5"
                    >
                      {Array.from({ length: blanks }, (_, k) => (
                        <span key={`b${k}`} />
                      ))}
                      {Array.from({ length: daysInMonth }, (_, k) => {
                        const day = `${view.y}-${pad(view.m + 1)}-${pad(k + 1)}`;
                        const selected = day === value;
                        const isToday = day === today;
                        return (
                          <div key={day} className="grid place-items-center">
                            <motion.button
                              type="button"
                              data-day={day}
                              whileTap={press}
                              transition={spring.micro}
                              disabled={!allowed(day)}
                              tabIndex={day === focusDay ? 0 : -1}
                              aria-label={longLabel(day)}
                              aria-pressed={selected}
                              aria-current={isToday ? "date" : undefined}
                              onClick={() => pick(day)}
                              onFocus={() => setFocusDay(day)}
                              className={`grid size-9 place-items-center rounded-full text-[15px] tabular-nums transition-colors disabled:text-ink-3 disabled:opacity-40 ${
                                selected
                                  ? "bg-action font-semibold text-white"
                                  : isToday
                                    ? "font-semibold text-action hover:bg-action/10"
                                    : "hover:bg-black/[0.05] dark:hover:bg-white/10"
                              }`}
                            >
                              {k + 1}
                            </motion.button>
                          </div>
                        );
                      })}
                    </div>
                    {allowed(today) && (
                      <div className="flex justify-end pt-1">
                        <button type="button" onClick={() => pick(today)} className="rounded-lg px-2 py-1 text-[13px] text-link hover:bg-black/[0.04] dark:hover:bg-white/10">
                          Today
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function NavButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
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
      disabled={disabled}
      onClick={onClick}
      className="grid size-8 place-items-center rounded-full text-action hover:bg-black/[0.05] disabled:text-ink-3 disabled:opacity-40 dark:hover:bg-white/10"
    >
      {children}
    </motion.button>
  );
}
