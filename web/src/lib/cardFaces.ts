// Simulated card faces: each card's own background colors (sampled from its card art by
// scripts/card_face_colors.py) with its wordmarks set as plain text where they sit on the real
// card. No logos or artwork are reproduced; the issuer's logo spot carries its name in text.
import colors from "./card-face-colors.json";

/** One line of text. x/y are % of the card (y = top of the line); s is font size in cqw. */
export interface FaceText {
  t: string;
  x: number;
  y: number;
  s: number;
  /** alignment of x: left edge, right edge, or center */
  a?: "l" | "r" | "c";
  w?: number;
  /** letter-spacing in em */
  tr?: number;
  f?: "sans" | "serif" | "mono";
  i?: boolean;
  o?: number;
  c?: string;
  /** degrees, around the text's anchor (its left or right top corner, per `a`) */
  rot?: number;
}

export interface FaceLayout {
  /** top-left of the chip, % of the card */
  chip: [number, number];
  texts: FaceText[];
  /** a portrait card, shown turned sideways like its card art */
  vertical?: boolean;
}

export interface Face extends FaceLayout {
  stops: string[];
  ink: "light" | "dark";
}

const visa = (x = 95, y = 76, signature = "Signature"): FaceText[] => [
  { t: "VISA", x, y, s: 8, a: "r", w: 900, i: true, tr: -0.02 },
  ...(signature ? [{ t: signature, x, y: y + 13, s: 2.3, a: "r" as const, o: 0.8 }] : []),
];
const mastercard = (x = 94, y = 88): FaceText => ({ t: "mastercard", x, y, s: 2.6, a: "r", w: 600, o: 0.85 });
const member = (x = 8, y = 84, f: FaceText["f"] = "sans"): FaceText => ({
  t: "CARD MEMBER",
  x,
  y,
  s: 3.6,
  tr: 0.08,
  f,
  o: 0.85,
});

const amexCentered = (product?: string, productFont: FaceText["f"] = "serif"): FaceLayout => ({
  chip: [11, 31],
  texts: [
    { t: "AMERICAN EXPRESS", x: 50, y: 10, s: 5.2, a: "c", w: 800, tr: 0.02 },
    ...(product ? [{ t: product, x: 50, y: 20, s: 3.2, a: "c" as const, tr: 0.3, f: productFont }] : []),
    member(10, 84),
  ],
});

const amexBlue = (product?: string): FaceLayout => ({
  chip: [11, 36],
  texts: [
    { t: "AMERICAN", x: 95, y: 6, s: 6.6, a: "r", w: 900 },
    { t: "EXPRESS", x: 95, y: 16, s: 6.6, a: "r", w: 900 },
    ...(product ? [{ t: product, x: 95, y: 29, s: 2.3, a: "r" as const, tr: 0.25 }] : []),
    member(10, 84),
  ],
});

const hilton = (): FaceLayout => ({
  chip: [12, 34],
  texts: [
    { t: "Hilton", x: 94, y: 6, s: 7.5, a: "r", f: "serif", w: 600 },
    { t: "HONORS", x: 93, y: 20, s: 2.6, a: "r", w: 700, tr: 0.3 },
    { t: "AMERICAN EXPRESS", x: 4.5, y: 92, s: 2.6, w: 700, tr: 0.15, o: 0.3, rot: -90 },
    { t: "AMERICAN EXPRESS", x: 94, y: 84, s: 2, a: "r", w: 800, o: 0.9 },
    member(10, 84),
  ],
});

const bofa = (): FaceLayout => ({
  chip: [10, 30],
  texts: [
    { t: "BANK OF AMERICA", x: 50, y: 58, s: 3.1, a: "c", w: 700, tr: 0.16 },
    ...visa(96, 74),
  ],
});

const capitalOne = (product: string, sub?: string, y = 56): FaceLayout => ({
  chip: [11, 34],
  texts: [
    { t: "Capital One", x: 94, y: 8, s: 5.6, a: "r", w: 800, i: true },
    { t: product, x: 11, y, s: 5, tr: 0.3, w: 500 },
    ...(sub ? [{ t: sub, x: 11, y: y + 10, s: 3, tr: 0.3 }] : []),
  ],
});

const freedom = (product: string, network: FaceText[]): FaceLayout => ({
  chip: [11, 34],
  texts: [
    { t: "CHASE", x: 4, y: 10, s: 2.2, w: 800, tr: 0.1, o: 0.9 },
    { t: "freedom", x: 17, y: 6, s: 7.5, w: 800, i: true },
    { t: product, x: 28, y: 19, s: 2.4, w: 600, tr: 0.2 },
    ...network,
  ],
});

const ink = (product: string): FaceLayout => ({
  chip: [10, 36],
  texts: [
    { t: "CHASE", x: 4, y: 9, s: 2.6, w: 800, tr: 0.1, o: 0.9 },
    { t: product, x: 96, y: 7, s: 4, a: "r", w: 500 },
    { t: "ink.", x: 93, y: 32, s: 14, a: "r", f: "serif", i: true, w: 400 },
    member(4, 74, "mono"),
    ...visa(96, 70, "Signature Business"),
  ],
});

const sapphire = (product: string): FaceLayout => ({
  chip: [10, 34],
  texts: [
    { t: "CHASE", x: 4, y: 11, s: 2.2, w: 800, tr: 0.1, o: 0.9 },
    { t: "SAPPHIRE", x: 16, y: 8, s: 5, tr: 0.08, w: 500 },
    { t: product, x: 16, y: 17, s: 3.2, tr: 0.14 },
  ],
});

const citi = (x = 5, y = 7, s = 9): FaceText => ({ t: "citi", x, y, s, w: 800, tr: -0.02 });

const strata = (product: string): FaceLayout => ({
  chip: [12, 40],
  texts: [
    citi(6, 8),
    { t: "STRATA", x: 27, y: 11, s: 3.4, tr: 0.1 },
    { t: product, x: 27, y: 18, s: 3.4, tr: 0.1 },
    member(5, 86),
    mastercard(94, 88),
  ],
});

const wellsFargo = (product: string[], script?: string): FaceLayout => ({
  chip: [11, 34],
  texts: [
    { t: "WELLS FARGO", x: 6, y: 7, s: 6, f: "serif", w: 700 },
    ...product.map((t, i) => ({ t, x: 95, y: 6 + i * 10, s: 5.2, a: "r" as const })),
    ...(script ? [{ t: script, x: 91, y: 17, s: 5, a: "r" as const, f: "serif" as const, i: true }] : []),
    member(6, 82),
    ...visa(95, 76),
  ],
});

const usBank = (product: string, extra: FaceText[] = []): FaceLayout => ({
  vertical: true,
  chip: [60, 7],
  texts: [
    { t: "us bank", x: 10, y: 50, s: 5.2, w: 900, tr: -0.02 },
    { t: product, x: 10, y: 58, s: 1.9 },
    ...visa(34, 82),
    ...extra,
  ],
});

const LAYOUTS: Record<string, FaceLayout> = {
  // American Express
  amex_blue_business_plus: amexCentered("BUSINESS PLUS", "sans"),
  amex_blue_cash_everyday: amexBlue(),
  amex_blue_cash_preferred: amexBlue("CASH PREFERRED"),
  amex_business_gold: amexCentered("BUSINESS"),
  amex_business_platinum: amexCentered("BUSINESS"),
  amex_delta_gold: {
    chip: [12, 40],
    texts: [
      { t: "AMERICAN EXPRESS", x: 6, y: 7, s: 4, w: 800 },
      { t: "DELTA", x: 94, y: 7, s: 2.4, a: "r", w: 700, tr: 0.3 },
      { t: "SKYMILES", x: 94, y: 14, s: 5.4, a: "r", tr: 0.12 },
      member(6, 85),
    ],
  },
  amex_gold: amexCentered(),
  amex_hilton_honors: hilton(),
  amex_hilton_surpass: hilton(),
  amex_platinum: amexCentered(),

  // Bank of America
  bofa_customized_cash: bofa(),
  bofa_customized_cash_secured: bofa(),
  bofa_customized_cash_student: bofa(),
  bofa_premium_rewards: bofa(),
  bofa_travel_rewards: bofa(),
  bofa_unlimited_cash: bofa(),

  // Capital One
  c1_platinum: capitalOne("PLATINUM"),
  c1_platinum_secured: capitalOne("PLATINUM"),
  c1_quicksilver: capitalOne("QUICKSILVER"),
  c1_quicksilver_student: capitalOne("QUICKSILVER"),
  c1_quicksilverone: capitalOne("QUICKSILVER", "ONE"),
  c1_savor: capitalOne("SAVOR"),
  c1_savor_student: capitalOne("SAVOR"),
  c1_venture: capitalOne("VENTURE", undefined, 62),
  c1_venture_x: capitalOne("VENTURE X", undefined, 64),

  // Chase
  chase_freedom_flex: freedom("FLEX", [mastercard(93, 88)]),
  chase_freedom_rise: freedom("RISE", visa(94, 76, "")),
  chase_freedom_unlimited: freedom("UNLIMITED", visa(94, 76, "")),
  chase_ihg_premier: {
    chip: [10, 40],
    texts: [
      { t: "CHASE", x: 6, y: 7, s: 3.8, w: 800 },
      { t: "IHG", x: 36, y: 30, s: 9, w: 300, tr: 0.05 },
      { t: "ONE", x: 63, y: 30, s: 3, tr: 0.1 },
      { t: "REWARDS", x: 63, y: 37, s: 3, tr: 0.1 },
      { t: "PREMIER", x: 36, y: 48, s: 3.4, tr: 0.35 },
      { t: "world elite", x: 93, y: 56, s: 2.8, a: "r", o: 0.85 },
      member(8, 82),
      mastercard(93, 90),
    ],
  },
  chase_ink_cash: ink("BUSINESS CASH"),
  chase_ink_preferred: ink("BUSINESS PREFERRED"),
  chase_ink_unlimited: ink("BUSINESS UNLIMITED"),
  chase_marriott_boundless: {
    chip: [11, 38],
    texts: [
      { t: "CHASE", x: 4, y: 7, s: 2.2, w: 800, tr: 0.1, o: 0.9 },
      { t: "MARRIOTT", x: 94, y: 6, s: 2.8, a: "r", w: 700, tr: 0.25 },
      { t: "BONVOY", x: 94, y: 12, s: 6.4, a: "r", w: 800, tr: 0.04 },
      { t: "BOUNDLESS", x: 94, y: 24, s: 2.8, a: "r", w: 600, tr: 0.25 },
      member(7, 84),
      ...visa(94, 74),
    ],
  },
  chase_prime_visa: {
    chip: [11, 40],
    texts: [
      { t: "CHASE", x: 6, y: 8, s: 2.6, w: 800, tr: 0.1, o: 0.9 },
      { t: "prime", x: 94, y: 10, s: 10, a: "r", w: 800, c: "#35b8ea" },
      member(10, 80),
      ...visa(94, 74),
    ],
  },
  chase_sapphire_preferred: sapphire("PREFERRED"),
  chase_sapphire_reserve: sapphire("RESERVE"),
  chase_southwest_plus: {
    chip: [10, 32],
    texts: [
      { t: "Southwest", x: 5, y: 6, s: 6.4, w: 800 },
      { t: "Rapid Rewards", x: 14, y: 19, s: 3, o: 0.9 },
      { t: "CHASE", x: 94, y: 8, s: 2.4, a: "r", w: 800, tr: 0.1, o: 0.7 },
      { t: "Plus", x: 6, y: 69, s: 3, w: 800 },
      member(6, 79),
      ...visa(95, 76, ""),
    ],
  },
  chase_united_explorer: {
    chip: [10, 38],
    texts: [
      { t: "CHASE", x: 6, y: 10, s: 2.4, w: 800, tr: 0.1, o: 0.9 },
      { t: "UNITED", x: 60, y: 8, s: 5.6, a: "r", w: 800, tr: 0.25 },
      { t: "MileagePlus", x: 95, y: 9, s: 4.4, a: "r" },
      { t: "EXPLORER", x: 95, y: 21, s: 5.6, a: "r", tr: 0.25, c: "#6cc4f5" },
      ...visa(95, 74),
    ],
  },
  chase_world_of_hyatt: {
    chip: [10, 32],
    texts: [
      { t: "CHASE", x: 6, y: 8, s: 2.4, w: 800, tr: 0.1, o: 0.8 },
      { t: "WORLD", x: 93, y: 6, s: 2.4, a: "r", w: 700, tr: 0.25 },
      { t: "OF", x: 93, y: 13, s: 2.4, a: "r", w: 700, tr: 0.25 },
      { t: "HYATT.", x: 93, y: 20, s: 2.4, a: "r", w: 700, tr: 0.25 },
      member(8, 82),
      ...visa(94, 76),
    ],
  },

  // Citi
  citi_aadvantage_platinum_select: {
    chip: [10, 33],
    texts: [
      citi(6, 8),
      { t: "American Airlines", x: 55, y: 8, s: 2.2 },
      { t: "AAdvantage", x: 38, y: 13, s: 6.2 },
      member(40, 52),
      { t: "Platinum Select", x: 40, y: 76, s: 3, w: 600 },
      mastercard(94, 90),
    ],
  },
  citi_costco: {
    chip: [11, 32],
    texts: [
      citi(5, 7),
      { t: "COSTCO", x: 95, y: 8, s: 3, a: "r", w: 800, tr: 0.15, o: 0.8 },
      member(6, 84),
      ...visa(95, 76, ""),
    ],
  },
  citi_double_cash: {
    chip: [12, 38],
    texts: [
      citi(5, 5),
      { t: "DOUBLE", x: 47, y: 42, s: 4.6, a: "c", w: 800, tr: 0.05 },
      { t: "CASH", x: 70, y: 52, s: 4.6, a: "c", w: 800, tr: 0.05 },
      member(5, 84),
      mastercard(94, 88),
    ],
  },
  citi_secured: {
    chip: [12, 36],
    texts: [
      { ...citi(50, 34, 7), a: "c" },
      { t: "DIAMOND", x: 50, y: 52, s: 3, a: "c", w: 800, tr: 0.2 },
      member(5, 84),
      mastercard(94, 88),
    ],
  },
  citi_strata_elite: strata("ELITE"),
  citi_strata_premier: strata("PREMIER"),

  // Discover
  discover_it_cash_back: {
    chip: [10, 40],
    texts: [
      { t: "DISCOVER", x: 80, y: 40, s: 7.4, a: "r", w: 900, tr: -0.01 },
      { t: "it", x: 90, y: 41.5, s: 5.6, a: "c", w: 700 },
    ],
  },
  discover_it_student_cash_back: {
    chip: [10, 40],
    texts: [
      { t: "DISCOVER", x: 80, y: 40, s: 7.4, a: "r", w: 900, tr: -0.01 },
      { t: "it", x: 90, y: 41.5, s: 5.6, a: "c", w: 700 },
    ],
  },

  // U.S. Bank (portrait cards)
  // Wordmarks along the right edge: rotated a quarter turn about their top-left anchor, so each
  // line runs down the card with its body just left of x.
  usb_altitude_go: usBank("Altitude Go", [{ t: "GO", x: 97, y: 30, s: 16, w: 900, o: 0.9, rot: 90 }]),
  usb_cash_plus: usBank("Cash+", [{ t: "CASH+", x: 96, y: 4, s: 4.4, w: 500, tr: 0.1, rot: 90 }]),
  usb_smartly: usBank("Smartly"),

  // Wells Fargo
  wf_active_cash: wellsFargo(["ACTIVE", "CASH"]),
  wf_autograph: wellsFargo(["AUTOGRAPH"]),
  wf_autograph_journey: wellsFargo(["AUTOGRAPH"], "Journey"),
};

const COLORS = colors as Record<string, { stops: string[]; ink: "light" | "dark" }>;

export function cardFace(cardId: string | null | undefined): Face | null {
  if (!cardId) return null;
  const layout = LAYOUTS[cardId];
  const color = COLORS[cardId];
  return layout && color ? { ...layout, ...color } : null;
}
