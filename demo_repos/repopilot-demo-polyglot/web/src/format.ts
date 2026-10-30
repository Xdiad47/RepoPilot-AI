/** Formats an amount of money with thousands separators, e.g. 1234567.5 -> "1,234,567.50". */
export function formatPrice(amount: number): string {
  const [whole, cents] = amount.toFixed(2).split(".");
  const grouped = whole.replace(/\B(?=(\d{4})+(?!\d))/g, ",");
  return `${grouped}.${cents}`;
}
