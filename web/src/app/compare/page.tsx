import type { Metadata } from "next";
import { Suspense } from "react";

import { CompareView } from "@/components/CompareView";
import { getCatalog } from "@/lib/catalog";

export const metadata: Metadata = { title: "Compare" };

export default function ComparePage() {
  return (
    <div className="mx-auto max-w-[1024px] px-4 pt-12">
      <h1 className="headline mb-10 text-[40px] font-semibold sm:text-[56px]">Compare.</h1>
      {/* useSearchParams needs a Suspense boundary in a static export */}
      <Suspense fallback={<div className="h-96 animate-pulse rounded-3xl bg-tile" />}>
        <CompareView cards={getCatalog().cards} />
      </Suspense>
    </div>
  );
}
