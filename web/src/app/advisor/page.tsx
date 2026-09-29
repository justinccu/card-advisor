import type { Metadata } from "next";

import { AdvisorChat } from "@/components/AdvisorChat";

export const metadata: Metadata = {
  title: "Advisor",
  description: "Ask which US credit card fits your spending, and whether issuer rules let you get it.",
};

export default function AdvisorPage() {
  return (
    <div className="mx-auto max-w-[720px] px-4 pt-6">
      <AdvisorChat />
    </div>
  );
}
