import { TriangleAlert } from "lucide-react";

// Shown whenever the site was built from `scout preview` (unreviewed extraction, ADR 0002).
export function PreviewBanner() {
  return (
    <div className="border-b border-hairline bg-[#fff8e6] text-[12px] text-[#6b4e00] dark:bg-[#2a2204] dark:text-[#f5d67a]">
      <p className="mx-auto flex max-w-[1024px] items-center justify-center gap-2 px-4 py-2 text-center">
        <TriangleAlert size={14} aria-hidden />
        Local preview: card details come from automated extraction and have not been human-reviewed yet.
      </p>
    </div>
  );
}
