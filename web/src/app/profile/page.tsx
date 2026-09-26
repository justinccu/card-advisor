"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useSession } from "@/components/Providers";
import { Segmented } from "@/components/Segmented";
import { api } from "@/lib/api";
import { press, spring } from "@/lib/motion";
import type { ApplicantProfile, TaxId } from "@/lib/types";

const SCORE = [
  { value: "none", label: "No score" },
  { value: "580_669", label: "580–669" },
  { value: "670_739", label: "670–739" },
  { value: "740_799", label: "740–799" },
  { value: "800_plus", label: "800+" },
];
const INCOME = [
  { value: "under_25k", label: "< $25k" },
  { value: "25k_50k", label: "$25–50k" },
  { value: "50k_100k", label: "$50–100k" },
  { value: "100k_200k", label: "$100–200k" },
  { value: "200k_plus", label: "$200k+" },
];

export default function ProfilePage() {
  const { uid, ready, signOut } = useSession();
  const qc = useQueryClient();
  const router = useRouter();
  const key = ["profile", uid];
  const { data } = useQuery({ queryKey: key, queryFn: api.profile, enabled: !!uid });

  // Optimistic: the control reflects the tap immediately; a failed save restores the old value.
  const save = useMutation({
    mutationFn: api.putProfile,
    onMutate: async (next: ApplicantProfile) => {
      await qc.cancelQueries({ queryKey: key });
      const previous = qc.getQueryData<ApplicantProfile>(key);
      qc.setQueryData(key, next);
      return { previous };
    },
    onError: (_e, _n, ctx) => qc.setQueryData(key, ctx?.previous),
    onSettled: () => qc.invalidateQueries({ queryKey: ["eligibility", uid] }),
  });

  useEffect(() => {
    if (ready && !uid) router.replace("/signin/");
  }, [ready, uid, router]);

  if (!ready || !uid) return null;
  const p: ApplicantProfile = data ?? { tax_id: null, score_band: null, income_band: null, credit_history: null };
  const set = (patch: Partial<ApplicantProfile>) => save.mutate({ ...p, ...patch });

  return (
    <div className="mx-auto max-w-[640px] space-y-10 px-4 pt-12">
      <div>
        <h1 className="headline text-[40px] font-semibold sm:text-[56px]">About you.</h1>
        <p className="mt-2 text-[17px] text-ink-2">
          Only ranges, never exact numbers. We never ask for or store an SSN.
        </p>
      </div>

      <Field title="Tax ID you can apply with" hint="Some issuers accept an ITIN instead of an SSN.">
        <Segmented<TaxId>
          label="Tax ID"
          options={[
            { value: "SSN", label: "SSN" },
            { value: "ITIN", label: "ITIN" },
            { value: "NONE", label: "Neither" },
          ]}
          value={(p.tax_id ?? "") as TaxId}
          onChange={(v) => set({ tax_id: v })}
        />
      </Field>

      <Field title="Credit score (approx.)">
        <Chips options={SCORE} value={p.score_band} onChange={(v) => set({ score_band: v })} />
      </Field>

      <Field title="Annual income">
        <Chips options={INCOME} value={p.income_band} onChange={(v) => set({ income_band: v })} />
      </Field>

      <div className="flex items-center justify-between border-t border-hairline pt-6 text-[15px]">
        <button onClick={() => { signOut(); router.push("/"); }} className="text-link">
          Sign out
        </button>
        <button
          onClick={async () => {
            if (!window.confirm("Delete your wallet and profile? This can’t be undone.")) return;
            await api.deleteMe();
            signOut();
            router.push("/");
          }}
          className="text-bad"
        >
          Delete my data
        </button>
      </div>
    </div>
  );
}

function Field({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-[17px] font-semibold">{title}</h2>
      {hint && <p className="mb-3 text-[13px] text-ink-2">{hint}</p>}
      <div className={hint ? "" : "mt-3"}>{children}</div>
    </section>
  );
}

function Chips({ options, value, onChange }: { options: { value: string; label: string }[]; value: string | null; onChange: (v: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <motion.button
            key={o.value}
            whileTap={press}
            transition={spring.micro}
            onClick={() => onChange(o.value)}
            aria-pressed={on}
            className={`rounded-full px-4 py-2 text-[14px] ring-1 transition-colors ${on ? "bg-ink text-canvas ring-ink" : "ring-hairline"}`}
          >
            {o.label}
          </motion.button>
        );
      })}
    </div>
  );
}
