"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { AnimatePresence, motion, useAnimate, type PanInfo } from "motion/react";
import Link from "next/link";
import { useMemo, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { fullDate } from "@/lib/format";
import { issuerName } from "@/lib/issuers";
import { press, project, spring } from "@/lib/motion";
import { searchCards } from "@/lib/search";
import type { CatalogCard, Evaluation, HeldCard, HeldCardIn, HeldCardPatch, Issuer, Wallet, WalletAttestation } from "@/lib/types";

import { CardArt } from "./CardArt";
import { DatePicker, todayIso } from "./DatePicker";
import { useSession } from "./Providers";
import { Segmented } from "./Segmented";
import { Sheet } from "./Sheet";
import { useToast } from "./Toast";
import { VelocityGauge } from "./VelocityGauge";
import { Reasons, StatusPill } from "./Verdict";

const WALLET = ["wallet"] as const;

export function WalletView({ catalog, issuers }: { catalog: CatalogCard[]; issuers: Record<string, Issuer> }) {
  const { uid, ready } = useSession();
  if (!ready) return <div className="h-64 animate-pulse rounded-3xl bg-tile" />;
  if (!uid) {
    return (
      <div className="py-24 text-center">
        <p className="text-[21px] font-semibold">Sign in to build your wallet.</p>
        <p className="mx-auto mt-2 max-w-md text-[17px] text-ink-2">
          List the cards you have and we&apos;ll check every issuer rule before you apply.
        </p>
        <Link href="/signin/" className="mt-6 inline-block rounded-full bg-action px-6 py-3 text-[17px] font-medium text-white">
          Sign in
        </Link>
      </div>
    );
  }
  return <SignedInWallet uid={uid} catalog={catalog} issuers={issuers} />;
}

function SignedInWallet({
  uid,
  catalog,
  issuers,
}: {
  uid: string;
  catalog: CatalogCard[];
  issuers: Record<string, Issuer>;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const byId = useMemo(() => new Map(catalog.map((c) => [c.id, c])), [catalog]);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<HeldCard | null>(null);
  // Row identity must survive the temp-id -> server-id swap, or the optimistic row would fade out
  // while an identical "new" row fades in. Map each server id to the key its temp row used.
  const [rowKey, setRowKey] = useState<Record<string, string>>({});

  const wallet = useQuery({ queryKey: [...WALLET, uid], queryFn: api.wallet });
  const velocity = useQuery({ queryKey: ["velocity", uid], queryFn: api.velocity });
  const refreshDerived = () => {
    qc.invalidateQueries({ queryKey: ["velocity", uid] });
    qc.invalidateQueries({ queryKey: ["eligibility", uid] });
  };

  // Optimistic add: the card appears instantly with a temporary id; on failure it springs back
  // out (AnimatePresence exit) and the previous list is restored.
  const add = useMutation({
    mutationFn: ({ card }: { card: HeldCardIn; tempId: string }) => api.addCard(card),
    onMutate: async ({ card, tempId }) => {
      await qc.cancelQueries({ queryKey: [...WALLET, uid] });
      const previous = qc.getQueryData<Wallet>([...WALLET, uid]);
      const temp: HeldCard = { ...card, id: tempId };
      qc.setQueryData<Wallet>([...WALLET, uid], (w) => w && { ...w, cards: [...w.cards, temp] });
      return { previous };
    },
    onSuccess: (saved, { tempId }) => {
      setRowKey((k) => ({ ...k, [saved.id]: tempId }));
      qc.setQueryData<Wallet>([...WALLET, uid], (w) =>
        w && { ...w, cards: w.cards.map((c) => (c.id === tempId ? saved : c)) },
      );
    },
    onError: (err, _card, ctx) => {
      qc.setQueryData([...WALLET, uid], ctx?.previous);
      toast.show(err instanceof ApiError ? err.message : "Couldn’t add that card.");
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: [...WALLET, uid] });
      refreshDerived();
    },
  });

  const remove = useMutation({
    mutationFn: api.removeCard,
    onMutate: async (id: string) => {
      await qc.cancelQueries({ queryKey: [...WALLET, uid] });
      const previous = qc.getQueryData<Wallet>([...WALLET, uid]);
      qc.setQueryData<Wallet>([...WALLET, uid], (w) => w && { ...w, cards: w.cards.filter((c) => c.id !== id) });
      return { previous };
    },
    onError: (err, _id, ctx) => {
      qc.setQueryData([...WALLET, uid], ctx?.previous); // the row springs back into place
      toast.show(err instanceof ApiError ? err.message : "Couldn’t remove that card.");
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: [...WALLET, uid] });
      refreshDerived();
    },
  });

  // Optimistic edit: the row shows the new dates at once and reverts if the API refuses them.
  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: HeldCardPatch }) => api.updateCard(id, patch),
    onMutate: async ({ id, patch }) => {
      await qc.cancelQueries({ queryKey: [...WALLET, uid] });
      const previous = qc.getQueryData<Wallet>([...WALLET, uid]);
      qc.setQueryData<Wallet>([...WALLET, uid], (w) =>
        w && { ...w, cards: w.cards.map((c) => (c.id === id ? { ...c, ...patch } : c)) },
      );
      return { previous };
    },
    onError: (err, _v, ctx) => {
      qc.setQueryData([...WALLET, uid], ctx?.previous);
      toast.show(err instanceof ApiError ? err.message : "Couldn’t save that change.");
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: [...WALLET, uid] });
      refreshDerived();
    },
  });

  const attest = useMutation({
    mutationFn: api.putAttestation,
    onMutate: async (a: WalletAttestation) => {
      const previous = qc.getQueryData<Wallet>([...WALLET, uid]);
      qc.setQueryData<Wallet>([...WALLET, uid], (w) => w && { ...w, attestation: a });
      return { previous };
    },
    onError: (_e, _a, ctx) => {
      qc.setQueryData([...WALLET, uid], ctx?.previous);
      toast.show("Couldn’t save that.");
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: [...WALLET, uid] });
      refreshDerived();
    },
  });

  if (wallet.error) {
    return (
      <p className="py-24 text-center text-[17px] text-bad">
        {wallet.error instanceof ApiError ? wallet.error.message : "Couldn’t load your wallet."}
      </p>
    );
  }

  const cards = [...(wallet.data?.cards ?? [])].sort((a, b) => b.opened_on.localeCompare(a.opened_on));
  const attestation = wallet.data?.attestation;

  return (
    <div className="space-y-12">
      <section className="rounded-[28px] bg-tile p-6 sm:p-8">
        <VelocityGauge v={velocity.data} />
      </section>

      <section>
        <div className="flex items-end justify-between">
          <h2 className="text-[28px] font-semibold tracking-tight">Your cards</h2>
          <motion.button
            whileTap={press}
            transition={spring.micro}
            onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1 rounded-full bg-action px-4 py-2 text-[14px] font-medium text-white hover:bg-action-hover"
          >
            <Plus size={16} /> Add card
          </motion.button>
        </div>
        <p className="mt-1 text-[13px] text-ink-2">Tap a card to edit its dates. Swipe left to remove it.</p>
        <ul className="mt-4 overflow-hidden rounded-[20px] bg-surface ring-1 ring-hairline">
          <AnimatePresence initial={false}>
            {cards.map((c) => (
              <HeldRow
                key={rowKey[c.id] ?? c.id}
                card={c}
                product={c.card_product_id ? byId.get(c.card_product_id) : undefined}
                onEdit={() => setEditing(c)}
                onRemove={() => remove.mutate(c.id)}
              />
            ))}
          </AnimatePresence>
          {wallet.isPending && <li className="h-20 animate-pulse bg-tile" />}
          {wallet.data && cards.length === 0 && (
            <li className="p-8 text-center text-[15px] text-ink-2">No cards yet. Add the ones you have, including closed ones from the last two years.</li>
          )}
        </ul>
      </section>

      {attestation && (
        <section className="space-y-3">
          <h2 className="text-[21px] font-semibold tracking-tight">Is this everything?</h2>
          <p className="text-[15px] text-ink-2">
            Rules like 5/24 count cards from every bank, so we only say &ldquo;eligible&rdquo; when you confirm your list is complete.
          </p>
          <Toggle
            label="I’ve listed every card I opened in the last 24 months, from any bank, including authorized-user cards."
            checked={!!attestation.complete_since}
            onChange={(on) => {
              const since = new Date();
              since.setMonth(since.getMonth() - 24);
              attest.mutate({ ...attestation, complete_since: on ? since.toISOString().slice(0, 10) : null });
            }}
          />
          <Toggle
            label="I’ve listed every card I currently have open."
            checked={attestation.includes_all_open_cards}
            onChange={(on) => attest.mutate({ ...attestation, includes_all_open_cards: on })}
          />
        </section>
      )}

      <EligibilityList uid={uid} />

      <AddCardSheet
        open={adding}
        onClose={() => setAdding(false)}
        catalog={catalog}
        issuers={issuers}
        onAdd={(card) => {
          setAdding(false);
          add.mutate({ card, tempId: `temp-${crypto.randomUUID()}` });
        }}
      />
      <EditCardSheet
        card={editing}
        product={editing?.card_product_id ? byId.get(editing.card_product_id) : undefined}
        onClose={() => setEditing(null)}
        onSave={(patch) => {
          if (editing && Object.keys(patch).length) update.mutate({ id: editing.id, patch });
          setEditing(null);
        }}
        onRemove={() => {
          if (editing) remove.mutate(editing.id);
          setEditing(null);
        }}
      />
      {toast.node}
    </div>
  );
}

const REVEAL = 88; // width of the delete action

/** Swipe-to-delete row: follows the finger 1:1, rubber-bands past the action, and on release
 *  either settles open (revealing Delete) or springs shut, based on projected momentum. */
function HeldRow({
  card,
  product,
  onEdit,
  onRemove,
}: {
  card: HeldCard;
  product?: CatalogCard;
  onEdit: () => void;
  onRemove: () => void;
}) {
  const [scope, animate] = useAnimate();
  const [open, setOpen] = useState(false);
  const dragged = useRef(false); // a swipe ends in a click too; it must not open the editor
  const name = product?.name ?? card.name ?? "Card";
  const issuer = product?.issuer_id ?? card.issuer_id ?? "";
  const pending = card.id.startsWith("temp-");

  const settle = (to: number, velocity = 0) => {
    setOpen(to !== 0);
    animate(scope.current, { x: to }, { ...spring.sheet, velocity });
  };
  const onDragEnd = (_: unknown, info: PanInfo) => {
    const resting = info.offset.x + project(info.velocity.x);
    settle(resting < -REVEAL / 2 ? -REVEAL : 0, info.velocity.x);
  };

  return (
    <motion.li
      layout
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      transition={spring.nav}
      className="relative overflow-hidden border-b border-hairline last:border-b-0"
    >
      <button
        onClick={onRemove}
        className="absolute inset-y-0 right-0 flex w-[88px] items-center justify-center gap-1 bg-bad text-[14px] font-medium text-white"
        tabIndex={open ? 0 : -1}
        aria-hidden={!open}
      >
        <Trash2 size={16} /> Delete
      </button>
      <motion.div
        ref={scope}
        drag={pending ? false : "x"}
        dragDirectionLock
        dragConstraints={{ left: -REVEAL, right: 0 }}
        dragElastic={{ left: 0.25, right: 0.05 }}
        dragMomentum={false}
        onDragStart={() => (dragged.current = true)}
        onDragEnd={onDragEnd}
        className={`relative flex items-center gap-4 bg-surface px-4 py-3.5 touch-pan-y ${pending ? "opacity-60" : ""}`}
      >
        <CardArt cardId={card.card_product_id} issuerId={issuer} name={name} bare className="w-16 shrink-0" />
        <button
          type="button"
          disabled={pending}
          aria-label={`Edit ${name}`}
          onClick={() => {
            if (dragged.current) dragged.current = false;
            else if (open) settle(0); // a tap on an open row closes it first
            else onEdit();
          }}
          className="min-w-0 flex-1 text-left"
        >
          <p className="truncate text-[15px] font-medium">{name}</p>
          <p className="text-[13px] text-ink-2">
            {issuerName(issuer)} · opened {fullDate(card.opened_on)}
            {card.closed_on && ` · closed ${fullDate(card.closed_on)}`}
            {card.is_authorized_user && " · authorized user"}
          </p>
        </button>
        <button
          type="button"
          onClick={onEdit}
          aria-hidden
          tabIndex={-1}
          disabled={pending}
          className="hidden size-8 place-items-center rounded-full text-ink-3 hover:bg-black/5 hover:text-ink sm:grid dark:hover:bg-white/10"
        >
          <Pencil size={15} />
        </button>
        <button
          onClick={onRemove}
          aria-label={`Remove ${name}`}
          disabled={pending}
          className="hidden size-8 place-items-center rounded-full text-ink-3 hover:bg-black/5 hover:text-bad sm:grid dark:hover:bg-white/10"
        >
          <Trash2 size={16} />
        </button>
      </motion.div>
    </motion.li>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-6 rounded-2xl bg-surface p-4 ring-1 ring-hairline">
      <span className="text-[15px]">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-[31px] w-[51px] shrink-0 rounded-full transition-colors duration-200 ${checked ? "bg-ok" : "bg-black/15 dark:bg-white/20"}`}
      >
        <motion.span
          layout
          transition={spring.micro}
          className={`absolute top-[2px] size-[27px] rounded-full bg-white shadow-[0_3px_8px_rgba(0,0,0,0.15)] ${checked ? "right-[2px]" : "left-[2px]"}`}
        />
      </button>
    </label>
  );
}

function AddCardSheet({
  open,
  onClose,
  catalog,
  issuers,
  onAdd,
}: {
  open: boolean;
  onClose: () => void;
  catalog: CatalogCard[];
  issuers: Record<string, Issuer>;
  onAdd: (card: HeldCardIn) => void;
}) {
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<CatalogCard | null>(null);
  const [opened, setOpened] = useState(todayIso);
  const [au, setAu] = useState(false);
  const results = useMemo(() => searchCards(q, catalog, issuers).cards.slice(0, 30), [catalog, issuers, q]);

  const reset = () => {
    setPicked(null);
    setQ("");
    setAu(false);
    setOpened(todayIso());
  };

  return (
    <Sheet
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title="Add a card"
    >
      <h2 className="headline text-[28px] font-semibold">Add a card.</h2>
      <AnimatePresence mode="wait" initial={false}>
        {!picked ? (
          <motion.div key="search" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} transition={spring.nav}>
            <label className="relative mt-4 block">
              <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" aria-hidden />
              <input
                autoFocus
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search by card or bank"
                aria-label="Search cards"
                className="w-full rounded-xl bg-black/[0.05] py-2.5 pl-9 pr-3 text-[15px] outline-none focus:ring-2 focus:ring-action dark:bg-white/10"
              />
            </label>
            <ul className="mt-3 divide-y divide-hairline">
              {results.map((c) => (
                <li key={c.id}>
                  <motion.button
                    whileTap={{ scale: 0.98 }}
                    transition={spring.micro}
                    onClick={() => setPicked(c)}
                    className="flex w-full items-center gap-3 py-2.5 text-left"
                  >
                    <CardArt cardId={c.id} issuerId={c.issuer_id} name={c.name} bare className="w-12 shrink-0" />
                    <span className="flex-1">
                      <span className="block text-[15px]">{c.name}</span>
                      <span className="text-[12px] text-ink-2">
                        {issuerName(c.issuer_id)}
                        {c.availability !== "open" && " · no longer offered"}
                      </span>
                    </span>
                  </motion.button>
                </li>
              ))}
            </ul>
          </motion.div>
        ) : (
          <motion.form
            key="details"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            transition={spring.nav}
            className="mt-4 space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              onAdd({ card_product_id: picked.id, opened_on: opened, is_authorized_user: au });
              reset();
            }}
          >
            <div className="flex items-center gap-4">
              <CardArt cardId={picked.id} issuerId={picked.issuer_id} name={picked.name} className="w-24" />
              <div>
                <p className="text-[17px] font-semibold">{picked.name}</p>
                <button type="button" onClick={() => setPicked(null)} className="text-[13px] text-link">
                  Change
                </button>
              </div>
            </div>
            <DatePicker label="Opened" value={opened} onChange={setOpened} max={todayIso()} />
            <label className="flex items-center gap-3 text-[15px]">
              <input type="checkbox" checked={au} onChange={(e) => setAu(e.target.checked)} className="size-5 accent-[var(--action)]" />
              I&apos;m an authorized user on someone else&apos;s account
            </label>
            <motion.button whileTap={press} transition={spring.micro} className="w-full rounded-2xl bg-action py-3.5 text-[17px] font-medium text-white">
              Add to wallet
            </motion.button>
          </motion.form>
        )}
      </AnimatePresence>
    </Sheet>
  );
}

/** Correct a held card: its open date, whether (and when) it closed, authorized-user status. */
function EditCardSheet({
  card,
  product,
  onClose,
  onSave,
  onRemove,
}: {
  card: HeldCard | null;
  product?: CatalogCard;
  onClose: () => void;
  onSave: (patch: HeldCardPatch) => void;
  onRemove: () => void;
}) {
  // The form keeps the last card while the sheet animates out.
  const [shown, setShown] = useState<HeldCard | null>(card);
  const [opened, setOpened] = useState("");
  const [isClosed, setIsClosed] = useState(false);
  const [closed, setClosed] = useState("");
  const [au, setAu] = useState(false);
  if (card && card !== shown) {
    setShown(card);
    setOpened(card.opened_on);
    setIsClosed(!!card.closed_on);
    setClosed(card.closed_on ?? "");
    setAu(!!card.is_authorized_user);
  }
  const c = card ?? shown;
  const name = product?.name ?? c?.name ?? "Card";
  const issuer = product?.issuer_id ?? c?.issuer_id ?? "";

  return (
    <Sheet open={!!card} onClose={onClose} title={`Edit ${name}`}>
      {c && (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            const patch: HeldCardPatch = {};
            if (opened !== c.opened_on) patch.opened_on = opened;
            const nextClosed = isClosed ? closed : null;
            if (nextClosed !== (c.closed_on ?? null)) patch.closed_on = nextClosed;
            if (au !== !!c.is_authorized_user) patch.is_authorized_user = au;
            onSave(patch);
          }}
        >
          <h2 className="headline text-[28px] font-semibold">Edit card.</h2>
          <div className="flex items-center gap-4">
            <CardArt cardId={c.card_product_id} issuerId={issuer} name={name} className="w-24" />
            <div>
              <p className="text-[17px] font-semibold">{name}</p>
              <p className="text-[13px] text-ink-2">{issuerName(issuer)}</p>
            </div>
          </div>
          <DatePicker label="Opened" value={opened} onChange={setOpened} max={isClosed && closed ? closed : todayIso()} />
          <label className="flex items-center gap-3 text-[15px]">
            <input
              type="checkbox"
              checked={isClosed}
              onChange={(e) => {
                setIsClosed(e.target.checked);
                if (e.target.checked && !closed) setClosed(todayIso());
              }}
              className="size-5 accent-[var(--action)]"
            />
            I&apos;ve closed this card
          </label>
          {isClosed && <DatePicker label="Closed" value={closed} onChange={setClosed} min={opened} max={todayIso()} />}
          <label className="flex items-center gap-3 text-[15px]">
            <input type="checkbox" checked={au} onChange={(e) => setAu(e.target.checked)} className="size-5 accent-[var(--action)]" />
            I&apos;m an authorized user on someone else&apos;s account
          </label>
          <motion.button whileTap={press} transition={spring.micro} className="w-full rounded-2xl bg-action py-3.5 text-[17px] font-medium text-white">
            Save
          </motion.button>
          <button type="button" onClick={onRemove} className="w-full py-2 text-[15px] text-bad">
            Remove from wallet
          </button>
        </form>
      )}
    </Sheet>
  );
}

function EligibilityList({ uid }: { uid: string }) {
  const [show, setShow] = useState<"eligible" | "all">("eligible");
  const { data, isPending, error } = useQuery({ queryKey: ["eligibility", uid], queryFn: () => api.eligibility() });
  const [expanded, setExpanded] = useState<string | null>(null);

  const rank = (e: Evaluation) =>
    (e.application.status === "Eligible" ? 0 : e.application.status === "Undetermined" ? 1 : 2) * 3 +
    (e.offer.status === "Eligible" ? 0 : e.offer.status === "Undetermined" ? 1 : 2);
  const list = (data ?? [])
    .filter((e) => show === "all" || e.application.status === "Eligible")
    .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));

  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 className="text-[28px] font-semibold tracking-tight">What you can get</h2>
        <Segmented
          options={[
            { value: "eligible", label: "Likely eligible" },
            { value: "all", label: "All cards" },
          ]}
          value={show}
          onChange={setShow}
          label="Filter"
        />
      </div>
      {isPending && <div className="mt-4 h-40 animate-pulse rounded-[20px] bg-tile" />}
      {error && <p className="mt-4 text-[15px] text-bad">{error instanceof ApiError ? error.message : "Couldn’t check eligibility."}</p>}
      <ul className="mt-4 space-y-2">
        {list.map((e) => {
          const isOpen = expanded === e.card_product_id;
          return (
            <motion.li layout key={e.card_product_id} transition={spring.nav} className="overflow-hidden rounded-[18px] bg-surface ring-1 ring-hairline">
              <button
                onClick={() => setExpanded(isOpen ? null : e.card_product_id)}
                aria-expanded={isOpen}
                className="flex w-full items-center gap-3 px-4 py-3 text-left"
              >
                <span className="flex-1">
                  <span className="block text-[15px] font-medium">{e.name}</span>
                  <span className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
                    <StatusPill status={e.application.status} what="Approval" />
                    <StatusPill status={e.offer.status} what="Offer" />
                  </span>
                </span>
                <motion.span animate={{ rotate: isOpen ? 180 : 0 }} transition={spring.micro}>
                  <ChevronDown size={18} className="text-ink-3" />
                </motion.span>
              </button>
              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={spring.nav}
                  >
                    <div className="space-y-3 border-t border-hairline px-4 py-3">
                      <Reasons verdict={e.application} />
                      <Reasons verdict={e.offer} />
                      <Link href={`/cards/${e.card_product_id}/`} className="inline-block text-[13px] text-link hover:underline">
                        Card details ›
                      </Link>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.li>
          );
        })}
      </ul>
      {data && list.length === 0 && (
        <p className="mt-6 text-center text-[15px] text-ink-2">Nothing is clearly available yet. Confirm your list above, or view all cards.</p>
      )}
    </section>
  );
}
