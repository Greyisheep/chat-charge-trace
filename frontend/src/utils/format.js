/** Formatting helpers. */

/** Format an amount (number or numeric string) as NGN with thousands separators. */
export function formatNaira(amount, currency = "NGN") {
  const value = Number(amount);
  if (!Number.isFinite(value)) return "--";
  try {
    return new Intl.NumberFormat("en-NG", {
      style: "currency",
      currency: currency || "NGN",
      maximumFractionDigits: 2,
      minimumFractionDigits: value % 1 === 0 ? 0 : 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toLocaleString()}`;
  }
}

/**
 * Format a money string like "4500.00" with thousands separators without
 * doing any float math on the value. Display only.
 */
export function formatMoneyString(value, currency = "NGN") {
  if (value == null) return "--";
  const str = String(value).trim();
  if (!/^-?\d+(\.\d+)?$/.test(str)) return str;
  const negative = str.startsWith("-");
  const [rawInt, rawDec = ""] = (negative ? str.slice(1) : str).split(".");
  const intPart = rawInt.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const decPart = rawDec.replace(/0+$/, "");
  const symbol = currency === "NGN" || !currency ? "₦" : `${currency} `;
  return `${negative ? "-" : ""}${symbol}${intPart}${decPart ? `.${decPart}` : ""}`;
}

export function formatTimestamp(ts) {
  const date = ts instanceof Date ? ts : new Date(ts || Date.now());
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
