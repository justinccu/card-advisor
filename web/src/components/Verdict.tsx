import { CircleCheck, CircleHelp, CircleX } from "lucide-react";

import { shortDate } from "@/lib/format";
import type { Reason, Status, Verdict as VerdictT } from "@/lib/types";

const STYLE: Record<Status, { icon: typeof CircleCheck; cls: string; label: string }> = {
  Eligible: { icon: CircleCheck, cls: "text-ok", label: "Likely eligible" },
  Ineligible: { icon: CircleX, cls: "text-bad", label: "Not eligible now" },
  Undetermined: { icon: CircleHelp, cls: "text-warn", label: "Need more info" },
};

export function StatusPill({ status, what }: { status: Status; what: string }) {
  const s = STYLE[status];
  const Icon = s.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-[13px] font-medium ${s.cls}`}>
      <Icon size={15} aria-hidden />
      <span>
        {what}: {s.label}
      </span>
    </span>
  );
}

/** Reasons that decided the verdict first; eligible "all clear" lines last. */
export function Reasons({ verdict }: { verdict: VerdictT }) {
  const order: Record<Status, number> = { Ineligible: 0, Undetermined: 1, Eligible: 2 };
  const reasons = [...verdict.reasons].sort((a, b) => order[a.status] - order[b.status]);
  return (
    <ul className="space-y-1.5">
      {reasons.map((r) => (
        <ReasonLine key={r.rule_id} r={r} />
      ))}
      {verdict.warnings.map((r) => (
        <ReasonLine key={`w-${r.rule_id}`} r={r} warning />
      ))}
    </ul>
  );
}

function ReasonLine({ r, warning = false }: { r: Reason; warning?: boolean }) {
  const s = STYLE[warning ? "Undetermined" : r.status];
  const Icon = s.icon;
  return (
    <li className="flex gap-2 text-[13px] leading-snug">
      <Icon size={14} className={`mt-0.5 shrink-0 ${s.cls}`} aria-hidden />
      <span className="text-ink-2">
        {warning && <span className="font-medium text-warn">Soft rule · </span>}
        {r.message}
        {r.retry_after && <span className="text-ink"> Eligible again around {shortDate(r.retry_after)}.</span>}
        {r.confidence === "community" && <span className="text-ink-3"> (community-reported)</span>}
      </span>
    </li>
  );
}
