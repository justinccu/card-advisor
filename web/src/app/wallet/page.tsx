import type { Metadata } from "next";

import { WalletView } from "@/components/WalletView";
import { getCatalog } from "@/lib/catalog";

export const metadata: Metadata = { title: "Wallet" };

export default function WalletPage() {
  return (
    <div className="mx-auto max-w-[760px] px-4 pt-12">
      <h1 className="headline mb-8 text-[40px] font-semibold sm:text-[56px]">Your wallet.</h1>
      <WalletView catalog={getCatalog().cards} />
    </div>
  );
}
