/**
 * Profit report, read from GET /profit/by-variant. The server decides every figure (revenue after
 * discounts and returns, cost from the real purchase layers); this file only turns the answer into
 * rows and puts the period on the server's half-open [start, end) range. Money is a string from the
 * API and goes through toMinor/fromMinor, never float arithmetic.
 *
 * This report is the one place where money can be NEGATIVE: a loss-making item has a negative
 * gross_profit, and revenue goes negative when returns exceed sales. money.js documents its wire
 * format as non-negative, so the sign is handled here instead of loosening that shared contract.
 */
import { fromMinor, toMinor } from "./money";
import { periodRange } from "@/cashier/lib/period";
import { materialText } from "@/cashier/lib/material";

/** Plain non-negative decimal text, with an optional sign in front of it. */
const SIGNED_RE = /^([+-]?)(\d+(?:\.\d+)?)$/;

/**
 * Integer cents for an amount that may be negative. The sign is parsed OFF, the magnitude goes
 * through toMinor (so rounding is the same ROUND_HALF_UP as everywhere else), and the sign is put
 * back on the result — never on a float. A missing figure is zero, a signed zero is zero (not -0),
 * and garbage throws rather than becoming NaN.
 */
export function signedMinor(value) {
  if (value === null || value === undefined) return 0;
  // A number goes to toMinor as it is: it reads the number's own decimal text, which also covers
  // exponent forms (1e3, 1e-7) that String() would hand back with an "e" in them.
  if (typeof value === "number") return toMinor(value);
  const text = String(value).trim();
  const m = SIGNED_RE.exec(text);
  if (!m) throw new TypeError(`profit: not a signed decimal amount ("${text}")`);
  const minor = toMinor(m[2]);
  // -0.00 must read as 0: negating a zero magnitude would produce -0.
  return m[1] === "-" && minor !== 0 ? -minor : minor;
}

/** Money for display: a number, exact to the cent. */
export const signedMoney = (v) => Number(fromMinor(signedMinor(v)));

/** A percentage as a number (not money: the server already rounded it), never a signed zero. */
const pct = (v) => (v === null || v === undefined ? null : Number(v) === 0 ? 0 : Number(v));

const DAY_MS = 86_400_000;
const addDay = (dateKey) => new Date(Date.parse(`${dateKey}T00:00:00Z`) + DAY_MS).toISOString().slice(0, 10);

/**
 * The query for a report period. The shop's range is inclusive on both days ("today" is since = until),
 * but the server's range ends BEFORE `end`, so the end is the day after: sending `until` as it is would
 * leave out the last day, and "today" would always read as nothing.
 */
export function profitQuery({ period = "7d", brandId = "", season = "", material = "", now = new Date() } = {}) {
  const { since, until } = periodRange(period, now);
  const p = new URLSearchParams({ start: since, end: addDay(until) });
  if (brandId) p.set("brand_id", brandId);
  // String(null) is "null" and String(undefined) is "undefined": both are truthy after trim, so an
  // absent season would be sent as a filter for a season literally named "null". Treat it as blank.
  const seasonText = season === null || season === undefined ? "" : String(season).trim();
  if (seasonText) p.set("season", seasonText);
  // نفس الحكاية للخامة: materialText بتشيل القيمة الغايبة والفاضية والنص "null"، فالفلتر
  // ما بيتبعتش غير لما يكون فيه خامة حقيقية مختارة.
  const materialValue = materialText(material);
  if (materialValue) p.set("material", materialValue);
  return p.toString();
}

export function profitRows(apiRows = []) {
  return apiRows.map((r) => ({
    id: r.variant_id,
    model: r.model ?? "",
    season: r.season ?? "",
    material: materialText(r.material),
    brandId: r.brand_id ?? null,
    size: r.size ?? "",
    colour: r.colour ?? "",
    unitsSold: Number(r.units_sold ?? 0),
    unitsReturned: Number(r.units_returned ?? 0),
    revenue: signedMoney(r.revenue),
    cost: signedMoney(r.cost),
    profit: signedMoney(r.gross_profit),
    margin: pct(r.margin_pct),
    unitsWithoutCost: Number(r.units_without_cost ?? 0),
    costIsEstimate: !!r.cost_returned_is_estimate,
    // What came back and where it went: only the pieces that returned to the shelf give cost back.
    unitsReturnedToShelf: Number(r.units_returned_to_shelf ?? 0),
    costReturned: signedMoney(r.cost_returned ?? "0"),
    returnedByCondition: { ...(r.returned_by_condition ?? {}) },
  }));
}

/** The totals row the server computed over the same (filtered) rows. */
export function profitTotals(apiTotals) {
  const t = apiTotals ?? {};
  return {
    unitsSold: Number(t.units_sold ?? 0),
    revenue: signedMoney(t.revenue),
    cost: signedMoney(t.cost),
    profit: signedMoney(t.gross_profit),
    margin: pct(t.margin_pct),
    unitsWithoutCost: Number(t.units_without_cost ?? 0),
    // The server says whether every unit sold had a real cost. Anything else is a profit that may be too high.
    costIsComplete: t.cost_is_complete === true,
    // Was missing, so the "the cost of returns is estimated" note could never appear: the notice
    // read a figure this mapping never filled in.
    unitsReturned: Number(t.units_returned ?? 0),
    unitsReturnedToShelf: Number(t.units_returned_to_shelf ?? 0),
    returnedByCondition: { ...(t.returned_by_condition ?? {}) },
  };
}

/** The margin as text, or a dash when there is no revenue to be a percentage of. */
export function marginLabel(margin) {
  return margin === null || margin === undefined ? "—" : `${Number(margin).toFixed(1)}٪`;
}
