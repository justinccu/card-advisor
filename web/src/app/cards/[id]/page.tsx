import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CardDetail } from "@/components/CardDetail";
import { offerHeadline } from "@/lib/format";
import { getCatalog } from "@/lib/catalog";

// One static page per card (SEO): "chase sapphire preferred welcome offer" lands here.
export function generateStaticParams() {
  return getCatalog().cards.map((c) => ({ id: c.id }));
}

export const dynamicParams = false;

export async function generateMetadata({ params }: PageProps<"/cards/[id]">): Promise<Metadata> {
  const { id } = await params;
  const card = getCatalog().cards.find((c) => c.id === id);
  if (!card) return {};
  return {
    title: card.name,
    description: `${card.name}: ${offerHeadline(card.offer)}. Annual fee, rewards and who can get it.`,
  };
}

export default async function CardPage({ params }: PageProps<"/cards/[id]">) {
  const { id } = await params;
  const card = getCatalog().cards.find((c) => c.id === id);
  if (!card) notFound();
  return (
    <div className="mx-auto max-w-[720px] px-4 pt-10">
      <Link href="/cards/" className="text-[15px] text-link hover:underline">
        ‹ All cards
      </Link>
      {card.availability !== "open" && (
        <p className="mt-6 rounded-xl bg-tile p-4 text-[15px] text-ink-2">
          This card is closed to new applicants{card.closed_on ? ` since ${card.closed_on}` : ""}. It&apos;s
          listed so cardholders can add it to their Wallet.
        </p>
      )}
      <div className="mt-6">
        <CardDetail card={card} />
      </div>
    </div>
  );
}
