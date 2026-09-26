"use client";

import { REAL_FACES_AVAILABLE, setCardStyle, useCardStyle } from "@/lib/cardStyle";

import { Segmented } from "./Segmented";

/** Demo only (see lib/cardStyle): compare the simulated faces with the local card art. */
export function CardStyleToggle() {
  const style = useCardStyle();
  if (!REAL_FACES_AVAILABLE) return null;
  return (
    <div className="flex items-center gap-3">
      <span>Card faces (demo)</span>
      <Segmented
        label="Card faces"
        value={style}
        onChange={setCardStyle}
        options={[
          { value: "simulated", label: "Simulated" },
          { value: "real", label: "Real" },
        ]}
      />
    </div>
  );
}
