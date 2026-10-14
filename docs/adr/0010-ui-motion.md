# UI motion: one set of tokens, fewer animations where people repeat themselves

Status: accepted 2026-10-02 with the product owner, who will revisit choices after trying the site
locally (each section names the alternative and what to change to switch). Sources: Emil
Kowalski's design-engineering skills (frequency rule, easing, durations) and transitions.dev
(motion tokens and patterns such as thinking states and text swaps); its license allows using and
modifying the transitions in our own site, not republishing them as a library.

## 1. Pace and tokens

**Chosen: crisp.** UI motion stays under 300ms, things enter a little slower than they leave, and
nothing animates that the keyboard triggers or people repeat many times a session. Tokens live in
`web/src/app/globals.css` (`--dur-*`, `--dist-*`, `--scale-*`, `--blur-s`; Tailwind `ease-enter`,
`ease-move`, `ease-drawer`) and, for Motion components, `tween` / `STAGGER` in `lib/motion.ts`.
- Alternative, **soft** (350–400ms, closer to Apple's marketing pages): raise `--dur-base` and
  `--dur-fast` and `tween.reveal` / `tween.in`. Costs responsiveness on frequent actions.

## 2. Which tool animates what

**Chosen: hybrid.** Gestures that can be dragged or interrupted (the sheet, the hero deck, wallet
rows) keep Motion's springs (`spring` in `lib/motion.ts`, unchanged this round). Fixed enter/exit
and state changes use the tokens:
- elements that mount and unmount (toast, compare tray, text and icon swaps) stay on Motion for
  its exit handling, but animate `opacity`, `filter` and a full `transform` string, which Motion
  hands to the browser off the main thread (its `x` / `y` / `scale` shorthands run on it; checked
  in Motion 13's `accelerated-values`);
- elements that stay mounted use CSS (`.shimmer`, `.enter-rise`).

Two consequences of the `transform` strings:
- Motion's `reducedMotion="user"` stills only its shorthands, so every `transform` string goes
  through `useCalm()` (`lib/motion.ts`), which makes the move instant and keeps the fade.
- Elements with `layout` (catalog tiles, compare chips) keep the shorthands: layout animations
  write `transform` themselves.

Alternatives: all-Motion (simpler, stutters while the page is busy) or all-CSS (exit animations
need manual unmount timing; gestures lose velocity-preserving interruption).

## 3. Fixes (no visible redesign)

- The catalog's static HTML showed 53 tiles at `opacity: 0` until JavaScript ran (blank grid on a
  slow load). `AnimatePresence initial={false}` renders them visible; later changes still animate.
- Typing in the catalog search no longer animates the grid (`INSTANT`); filter and sort clicks
  still reshuffle with a spring. To animate typing again, drop the `typed` state in
  `CatalogBrowser`.
- Compare chips enter from 90% (was 60%); the Advisor launcher rises above the compare tray with
  `translate` (was `bottom`, which re-laid out the page each frame).
- Not changed: the calendar and wallet-row height animations. The usual alternative (animating
  `grid-template-rows`) re-lays out the page just the same, and both are occasional.

## 4. Advisor chat

- **Status line**: a highlight sweeps across it while a step runs, and it swaps to the next step
  in 150ms (`SwapText` + `.shimmer`). The text exists once, so screen readers read it once.
  Reduced motion: static text, fade only.
- **Retry** (`reset`): the discarded draft fades out (it may hold what the retry fixes, so it
  doesn't stay dimmed on screen) and the line says "Double-checking the answer…".
- **Card rows** under an answer appear in turn (40ms apart); answers loaded from history don't
  replay it. The **quota** number, the **feedback** thanks and the **toast** text swap in place;
  the 👎 form unfolds; errors fade in (no shake: that's for the user's own input).
- **Send ⇄ Stop** is one button whose icon swaps.
- **Not animated, deliberately**: words as they stream (the Markdown re-renders on every chunk,
  and blur slows reading on the screen people watch most) and message bubbles (sending is
  usually Enter: keyboard-triggered and frequent). Revisit only with a prototype.
- **How the panel opens on wide screens: B, centered scale-and-fade** (2026-10-02, after the
  owner saw Edit card linger at the bottom of the screen: the phone's slide-up, used for a
  centered dialog, started it at the bottom edge and overshot). It applies to the shared `Sheet`:
  Edit card, Add a card and the Advisor panel open at 96% and fade in (250ms; close 150ms). Wide
  screens no longer drag the panel (close with its button, Escape or the backdrop); phones keep the
  draggable bottom sheet, and the e2e drag checks run at phone width. Alternatives kept in the
  local prototype (`/prototypes/advisor-panel`, git-excluded, never deployed): A slide up, C the
  Advisor growing out of its launcher, docked bottom-right without a backdrop.

## 5. Pages and forms

No page transitions (navigation is frequent). Sign-in and invite errors keep their shake and now
fade in. The site's visual style (colors, type, layout) is unchanged this round.

## Verification

`npm run lint`, `npm run build` (no `opacity:0` left in `/cards`), and all 47 `make e2e` checks.
Animations only got shorter or stayed the same, because the e2e script waits fixed times.
