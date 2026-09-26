// Display names and card-art palettes. Deliberately no logos or trademarked artwork:
// the art is an abstract gradient keyed to the issuer and tier.

export const ISSUERS: Record<string, string> = {
  chase: "Chase",
  amex: "American Express",
  citi: "Citi",
  capital_one: "Capital One",
  discover: "Discover",
  bofa: "Bank of America",
  wells_fargo: "Wells Fargo",
  us_bank: "U.S. Bank",
  bilt: "Bilt",
  apple: "Apple",
  petal: "Petal",
};

export const issuerName = (id: string) => ISSUERS[id] ?? id;

type Art = { from: string; to: string; ink: "light" | "dark" };

const BY_ISSUER: Record<string, Art> = {
  chase: { from: "#0b3a8c", to: "#2f6fe4", ink: "light" },
  amex: { from: "#0a5ea8", to: "#39a0e5", ink: "light" },
  citi: { from: "#0a2f5c", to: "#1f7fc1", ink: "light" },
  capital_one: { from: "#12263f", to: "#4a5d78", ink: "light" },
  discover: { from: "#e85d0c", to: "#f7a531", ink: "light" },
  bofa: { from: "#10245c", to: "#c8102e", ink: "light" },
  wells_fargo: { from: "#b3121f", to: "#e0452f", ink: "light" },
  us_bank: { from: "#1c2b6b", to: "#6c7aa8", ink: "light" },
};

// Tier cues read from the product name win over the issuer palette.
const BY_TIER: [RegExp, Art][] = [
  [/platinum|reserve|venture x|elite|palladium/i, { from: "#2b2d31", to: "#6b6f76", ink: "light" }],
  [/\bgold\b/i, { from: "#b88a2c", to: "#e8c872", ink: "dark" }],
  [/sapphire/i, { from: "#0c1f4a", to: "#2d4f9e", ink: "light" }],
  [/secured|student|rise|slate/i, { from: "#d9dde3", to: "#f4f6f8", ink: "dark" }],
];

export function cardArt(issuerId: string, name: string): Art {
  for (const [pattern, art] of BY_TIER) if (pattern.test(name)) return art;
  return BY_ISSUER[issuerId] ?? { from: "#3a3a3c", to: "#8e8e93", ink: "light" };
}
