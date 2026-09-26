import { BadgeCheck, Gavel, Scale } from "lucide-react";
import Link from "next/link";

import { HeroDeck } from "@/components/HeroDeck";
import { openCards } from "@/lib/catalog";
import { issuerName } from "@/lib/issuers";

const FEATURED = [
  "amex_gold",
  "chase_sapphire_preferred",
  "c1_venture_x",
  "chase_sapphire_reserve",
  "citi_strata_premier",
  "discover_it_cash_back",
  "wf_active_cash",
];

export default function Home() {
  const cards = openCards();
  const featured = FEATURED.map((id) => cards.find((c) => c.id === id)).filter(
    (c): c is (typeof cards)[number] => !!c,
  );
  const issuers = new Set(cards.map((c) => c.issuer_id)).size;

  return (
    <>
      <section className="mx-auto max-w-[1024px] px-4 pt-20 text-center sm:pt-28">
        <p className="text-[17px] font-semibold text-warn">No affiliate links. Ever.</p>
        <h1 className="headline mx-auto mt-3 max-w-3xl text-[44px] font-semibold sm:text-[72px]">
          Find the card that fits your life.
        </h1>
        <p className="mx-auto mt-5 max-w-2xl text-[19px] leading-snug text-ink-2 sm:text-[21px]">
          Compare {cards.length} US credit cards from {issuers} banks, and see which ones you can
          actually get before a hard pull.
        </p>
        <div className="mt-8 flex items-center justify-center gap-6 text-[17px]">
          <Link
            href="/cards/"
            className="rounded-full bg-action px-6 py-3 font-medium text-white transition-colors hover:bg-action-hover"
          >
            Browse cards
          </Link>
          <Link href="/wallet/" className="text-link hover:underline">
            Check eligibility ›
          </Link>
        </div>
      </section>

      <section className="mx-auto mt-14 max-w-[1100px]">
        <HeroDeck cards={featured} />
      </section>

      <section className="mx-auto mt-24 grid max-w-[1024px] gap-5 px-4 sm:grid-cols-3">
        <Pillar
          icon={<Gavel size={22} />}
          title="Knows the rules."
          body="Chase 5/24, Amex once-per-lifetime, Citi 48 months. We check your wallet against 26 issuer rules and tell you when you'll qualify."
        />
        <Pillar
          icon={<BadgeCheck size={22} />}
          title="Every number, sourced."
          body="Offers are read from each issuer's page, quoted word for word, and reviewed by a person before they're published."
        />
        <Pillar
          icon={<Scale size={22} />}
          title="Nobody pays for placement."
          body="We earn nothing when you apply. Rankings depend on your spending and your eligibility, nothing else."
        />
      </section>

      <section className="mx-auto mt-24 max-w-[1024px] px-4">
        <h2 className="headline text-[32px] font-semibold sm:text-[40px]">Every major issuer.</h2>
        <ul className="mt-6 flex flex-wrap gap-2">
          {[...new Set(cards.map((c) => c.issuer_id))].map((id) => (
            <li key={id} className="rounded-full bg-tile px-4 py-2 text-[15px]">
              {issuerName(id)} · {cards.filter((c) => c.issuer_id === id).length}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function Pillar({ icon, title, body }: { icon: React.ReactNode; title: string; body: string }) {
  return (
    <div className="rounded-[28px] bg-tile p-7">
      <div className="text-action">{icon}</div>
      <h3 className="mt-4 text-[21px] font-semibold tracking-tight">{title}</h3>
      <p className="mt-2 text-[15px] leading-relaxed text-ink-2">{body}</p>
    </div>
  );
}
