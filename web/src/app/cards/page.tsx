import type { Metadata } from "next";

import { CatalogBrowser } from "@/components/CatalogBrowser";
import { getCatalog, openCards } from "@/lib/catalog";

export const metadata: Metadata = { title: "Cards" };

export default function CardsPage() {
  const cards = openCards();
  return (
    <div className="mx-auto max-w-[1024px] px-4 pt-12">
      <h1 className="headline text-[40px] font-semibold sm:text-[56px]">All cards.</h1>
      <p className="mb-8 mt-2 max-w-xl text-[19px] text-ink-2">
        Welcome offers, fees and rewards from {cards.length} US cards, straight from each issuer.
      </p>
      <CatalogBrowser cards={cards} issuers={getCatalog().issuers ?? {}} />
    </div>
  );
}
