import type { AskDateSelector } from '@ledger/shared-types';

export type ResolvedAskRange = { from: string; to: string };

function parts(value: string) {
  const [year = 1970, month = 1, day = 1] = value.split('-').map(Number);
  return { year, month, day };
}

function dateValue(value: string) {
  const { year, month, day } = parts(value);
  return new Date(Date.UTC(year, month - 1, day));
}

function iso(value: Date) {
  return value.toISOString().slice(0, 10);
}

function shiftDays(value: string, days: number) {
  const date = dateValue(value);
  date.setUTCDate(date.getUTCDate() + days);
  return iso(date);
}

function shiftMonths(value: string, months: number) {
  const { year, month } = parts(value);
  return iso(new Date(Date.UTC(year, month - 1 + months, 1)));
}

function shiftYears(value: string, years: number) {
  const { year, month, day } = parts(value);
  const date = new Date(Date.UTC(year + years, month - 1, day));
  if (date.getUTCMonth() !== month - 1) return iso(new Date(Date.UTC(year + years, month, 0)));
  return iso(date);
}

function endOfMonth(value: string) {
  const { year, month } = parts(value);
  return iso(new Date(Date.UTC(year, month, 0)));
}

export function validatedTimeZone(value?: string) {
  const candidate = value?.trim() || 'UTC';
  try {
    new Intl.DateTimeFormat('en-CA', { timeZone: candidate }).format(new Date());
    return candidate;
  } catch {
    return 'UTC';
  }
}

export function dateInTimeZone(now: Date, timeZone: string) {
  const formatter = new Intl.DateTimeFormat('en', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  });
  const values = Object.fromEntries(
    formatter.formatToParts(now).filter((part) => part.type !== 'literal').map((part) => [part.type, part.value])
  );
  return `${values.year}-${values.month}-${values.day}`;
}

export function resolveAskRange(
  selector: AskDateSelector,
  asOfDate: string,
  earliestDate = asOfDate
): ResolvedAskRange {
  if (selector.kind === 'absolute') return { from: selector.from, to: selector.to };
  if (selector.kind === 'rolling_days') {
    return { from: shiftDays(asOfDate, -(selector.days - 1)), to: asOfDate };
  }
  const { year, month } = parts(asOfDate);
  const monthStart = `${year.toString().padStart(4, '0')}-${month.toString().padStart(2, '0')}-01`;
  const quarterMonth = Math.floor((month - 1) / 3) * 3 + 1;
  const quarterStart = `${year.toString().padStart(4, '0')}-${quarterMonth.toString().padStart(2, '0')}-01`;
  switch (selector.value) {
    case 'this_month': return { from: monthStart, to: asOfDate };
    case 'last_month': {
      const from = shiftMonths(monthStart, -1);
      return { from, to: endOfMonth(from) };
    }
    case 'this_quarter': return { from: quarterStart, to: asOfDate };
    case 'last_quarter': {
      const from = shiftMonths(quarterStart, -3);
      return { from, to: shiftDays(quarterStart, -1) };
    }
    case 'year_to_date': return { from: `${year}-01-01`, to: asOfDate };
    case 'last_year': return { from: `${year - 1}-01-01`, to: `${year - 1}-12-31` };
    case 'last_3_months': return { from: shiftMonths(monthStart, -2), to: asOfDate };
    case 'last_6_months': return { from: shiftMonths(monthStart, -5), to: asOfDate };
    case 'last_12_months': return { from: shiftMonths(monthStart, -11), to: asOfDate };
    case 'last_24_months': return { from: shiftMonths(monthStart, -23), to: asOfDate };
    case 'all': return { from: earliestDate, to: asOfDate };
  }
}

export function comparisonRange(
  range: ResolvedAskRange,
  comparison: 'none' | 'previous_period' | 'previous_year'
): ResolvedAskRange | null {
  if (comparison === 'none') return null;
  if (comparison === 'previous_year') {
    return { from: shiftYears(range.from, -1), to: shiftYears(range.to, -1) };
  }
  const days = Math.round((dateValue(range.to).getTime() - dateValue(range.from).getTime()) / 86_400_000) + 1;
  const to = shiftDays(range.from, -1);
  return { from: shiftDays(to, -(days - 1)), to };
}
