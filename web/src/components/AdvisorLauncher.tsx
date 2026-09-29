"use client";

import { Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { press, spring } from "@/lib/motion";

import { AdvisorChat } from "./AdvisorChat";
import { useAdvisor } from "./AdvisorProvider";
import { useCompare } from "./Providers";
import { Sheet } from "./Sheet";

/** The floating Advisor button on every page (except /advisor itself), opening the chat panel. */
export function AdvisorLauncher() {
  const { available, busy } = useAdvisor();
  const { ids } = useCompare();
  const path = usePathname();
  const [open, setOpen] = useState(false);
  // Following a link inside the panel (a card's Details) lands on a page with the panel closed.
  const [openedOn, setOpenedOn] = useState(path);
  if (open && path !== openedOn) setOpen(false);

  if (!available || path.startsWith("/advisor")) return null;
  return (
    <>
      <motion.button
        whileTap={press}
        transition={spring.micro}
        onClick={() => {
          setOpenedOn(path);
          setOpen(true);
        }}
        aria-label="Ask the Advisor"
        // Sits above the compare tray while that is showing.
        className={`glass fixed right-4 z-40 flex items-center gap-2 rounded-full px-4 py-3 text-[15px] font-medium shadow-[var(--shadow-lift)] ring-1 ring-hairline transition-[bottom] ${ids.length ? "bottom-24" : "bottom-5"}`}
      >
        <Sparkles size={18} className={`text-action ${busy ? "animate-pulse" : ""}`} aria-hidden />
        <span className="hidden sm:inline">Ask the Advisor</span>
      </motion.button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Advisor">
        <AdvisorChat panel />
      </Sheet>
    </>
  );
}
