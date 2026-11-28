/**
 * Report periods on REAL dates. `now` is a parameter so the rule is testable.
 * The shop's day is the Cairo calendar day: a shift opened at 00:30 local time belongs to that local
 * day even though its UTC date is the day before.
 */
export const SHOP_TZ = "Africa/Cairo";
export const PERIOD_DAYS = { today: 1, "7d": 7, "30d": 30 };

const dayKey = (date, tz = SHOP_TZ) => new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
const dayNumber = (key) => Math.floor(Date.parse(`${key}T00:00:00Z`) / 86_400_000);

/** The shop's calendar date ("2026-10-21") for an instant. NOT toISOString(): that is the UTC date, which is
 * still yesterday between 00:00 and 03:00 in Cairo, so "today" would be wrong every night. */
export const shopToday = (now = new Date(), tz = SHOP_TZ) => dayKey(now, tz);

/** True when the instant falls in the last `days` shop days, today included. Unknown period = 7 days. */
export function inShopPeriod(isoInstant, period = "7d", now = new Date(), tz = SHOP_TZ) {
  const when = new Date(isoInstant);
  if (Number.isNaN(when.getTime())) return false;
  const days = PERIOD_DAYS[period] ?? 7;
  const age = dayNumber(dayKey(now, tz)) - dayNumber(dayKey(when, tz));
  return age >= 0 && age < days;
}

/** [since, until] shop dates ("YYYY-MM-DD", inclusive) for a report period: today and the days before it. */
export function periodRange(period = "7d", now = new Date(), tz = SHOP_TZ) {
  const days = PERIOD_DAYS[period] ?? 7;
  const until = dayKey(now, tz);
  const since = new Date(Date.parse(`${until}T00:00:00Z`) - (days - 1) * 86_400_000).toISOString().slice(0, 10);
  return { since, until };
}
