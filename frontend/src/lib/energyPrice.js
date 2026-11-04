// The price of electricity, in $ per kWh, the way the server keeps it (see config_store.py on the server):
//   prices = { current: the average cost now | null, history: [{ from: "2026-11", price }] oldest first,
//              months: { "2026-03": 0.14 } (months given a price of their own) }
// Also used by the mock backend, so both work it out the same way (Node loads it as it is: plain JS, no .jsx imports).
import { createContext, useContext } from "react";

// The prices as the app last heard them, for any page that costs energy (the Power page, a printer's Energy section)
export const EnergyPricesContext = createContext({ current: null, history: [], months: {} });
export const useEnergyPrices = () => useContext(EnergyPricesContext);

// The price for a month ("2026-03"): its own, else the average cost that counted then (the first one set counts for
// every month before it too), else, with no history, the average cost as it is
export function priceForMonth(prices, month) {
  if (prices.months && month in prices.months) return prices.months[month];
  const history = prices.history || [];
  if (!history.length) return prices.current ?? null;
  let price = history[0].price;
  for (const e of history) {
    if (e.from > month) break;
    price = e.price;
  }
  return price;
}

// What electricity cost over `months` (each { key: "2026-03", whole, prints... }): each month's `field` kWh at that
// month's price. null when no month has both a figure and a price.
export const energyCost = (prices, months, field = "whole") =>
  months.reduce((sum, m) => {
    const price = priceForMonth(prices, m.key);
    return m[field] == null || price == null ? sum : (sum ?? 0) + m[field] * price;
  }, null);

// A price per kWh as typed in a box: a number from 0 to 100 (the server's limits) to 5 decimal places, null when the box
// is empty, undefined when it isn't a price
export const parsePrice = (text) => {
  if (!text.trim()) return null;
  const n = Number(text.trim());
  return Number.isFinite(n) && n >= 0 && n <= 100 ? Math.round(n * 100000) / 100000 : undefined;
};

// The history once the average cost is set to `price` in `month`: it counts from that month on, and every month
// before keeps the price it had (the same rule the server applies when it's saved)
export function withNewAverage(prices, price, month) {
  let history = (prices.history || []).filter((e) => e.from < month);
  if (!(prices.history || []).length && prices.current != null && price !== prices.current) history = [{ from: "0001-01", price: prices.current }];
  if (!(history.length && history[history.length - 1].price === price)) history = [...history, { from: month, price }];
  return { ...prices, current: price, history };
}

// This month in this browser's time zone: "2026-11"
export const thisMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
