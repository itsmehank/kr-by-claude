// 금액 계산은 BigInt 정수 곱만 — KR 가격·수량은 정수. float 금지(spec §5).
const INT = /^\d+$/;

export function estimateAmount(
  orderType: string, price: string | null, qty: string, upperLimit: string | null,
): { amount: string; basis: "limit" | "upper_limit" } | null {
  if (!INT.test(qty) || BigInt(qty) <= 0n) return null;
  if (orderType === "MARKET") {
    if (!upperLimit || !INT.test(upperLimit)) return null;
    return { amount: (BigInt(upperLimit) * BigInt(qty)).toString(), basis: "upper_limit" };
  }
  if (!price || !INT.test(price)) return null;
  return { amount: (BigInt(price) * BigInt(qty)).toString(), basis: "limit" };
}

export function fmtKrw(s: string | null | undefined): string {
  if (s == null || s === "") return "—";
  const [int, frac] = s.split(".");
  const neg = int.startsWith("-");
  const digits = neg ? int.slice(1) : int;
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${neg ? "-" : ""}${grouped}${frac ? "." + frac.replace(/0+$/, "").slice(0, 2) : ""}`.replace(/\.$/, "");
}
