import type { Status } from "./types";

const STATUS_CLASS: Record<string, string> = { "Act now": "act", "Needs a look": "look", OK: "ok" };
const STATUS_RANK: Record<string, number> = { "Act now": 3, "Needs a look": 2, OK: 1 };
const HINT_RANK: Record<string, number> = { yes: 3, maybe: 2, caution: 1 };

export const statusClass = (s: Status | string) => STATUS_CLASS[s] ?? "ok";
export const statusRank = (s: Status | string) => STATUS_RANK[s] ?? 0;

export function hintClass(hint: string): "yes" | "maybe" | "caution" {
  if (hint.startsWith("Yes")) return "yes";
  if (hint.startsWith("Maybe")) return "maybe";
  return "caution";
}
export const hintRank = (hint: string) => HINT_RANK[hintClass(hint)];

export const commas = (n: number) => n.toLocaleString("en-US");
export const capitalize = (s: string) => (s ? s[0].toUpperCase() + s.slice(1).toLowerCase() : s);
