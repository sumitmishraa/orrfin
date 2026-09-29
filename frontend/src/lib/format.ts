/**
 * Display formatting. Money arrives from the API as a decimal string ("240000.00") and is
 * formatted as text, digit by digit, so it never passes through a JavaScript float.
 */

/** "240000.5" → "₹2,40,000.50" (Indian digit grouping: last 3 digits, then pairs). */
export function formatINR(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const negative = value.startsWith("-");
  const [whole, fraction = ""] = value.replace("-", "").split(".");
  const paise = (fraction + "00").slice(0, 2);
  const lastThree = whole.slice(-3);
  const rest = whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
  const grouped = rest ? `${rest},${lastThree}` : lastThree;
  return `${negative ? "-" : ""}₹${grouped}.${paise}`;
}

/** "5.000" → "5"; "1.500" → "1.5". Quantities are shown without trailing zeros. */
export function formatQty(value: string): string {
  return value.includes(".") ? value.replace(/\.?0+$/, "") : value;
}

// BigInt(...) rather than 10n literals: tsconfig targets ES2017, which has no BigInt literal syntax.
const TEN = BigInt(10);

/** Multiply a quantity by a rate in exact decimal arithmetic (for live form totals only). */
export function lineTotal(qty: string, rate: string): string {
  const scale = (s: string) => (s.split(".")[1] ?? "").length;
  const toInt = (s: string) => BigInt(s.replace(".", "") || "0");
  if (!/^\d+(\.\d+)?$/.test(qty) || !/^\d+(\.\d+)?$/.test(rate)) return "0.00";
  const product = toInt(qty) * toInt(rate); // scaled by 10^(scale(qty)+scale(rate))
  const digits = scale(qty) + scale(rate);
  // Round half up to 2 decimals, the same rule the server uses.
  const shift = digits - 2;
  let cents: bigint;
  if (shift <= 0) cents = product * TEN ** BigInt(-shift);
  else {
    const divisor = TEN ** BigInt(shift);
    cents = (product + divisor / BigInt(2)) / divisor;
  }
  const text = cents.toString().padStart(3, "0");
  return `${text.slice(0, -2)}.${text.slice(-2)}`;
}

export function sumMoney(values: string[]): string {
  const cents = values.reduce((acc, v) => acc + BigInt(v.replace(".", "")), BigInt(0));
  const text = cents.toString().padStart(3, "0");
  return `${text.slice(0, -2)}.${text.slice(-2)}`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export const requestNumber = (n: number) => `PR-${String(n).padStart(4, "0")}`;

export const ROLE_LABELS: Record<string, string> = {
  requester: "Requester",
  buyer: "Buyer",
  approver: "Approver",
  finance: "Finance",
  admin: "Admin",
  manager: "Requester's manager",
};
