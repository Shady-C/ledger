import { describe, expect, it } from 'vitest';

import {
  comparisonRange,
  dateInTimeZone,
  resolveAskRange,
  validatedTimeZone
} from './time.js';

describe('Ask date resolution', () => {
  it.each([
    ['this_month', { from: '2026-07-01', to: '2026-07-25' }],
    ['last_month', { from: '2026-06-01', to: '2026-06-30' }],
    ['this_quarter', { from: '2026-07-01', to: '2026-07-25' }],
    ['last_quarter', { from: '2026-04-01', to: '2026-06-30' }],
    ['year_to_date', { from: '2026-01-01', to: '2026-07-25' }],
    ['last_year', { from: '2025-01-01', to: '2025-12-31' }],
    ['last_3_months', { from: '2026-05-01', to: '2026-07-25' }],
    ['last_6_months', { from: '2026-02-01', to: '2026-07-25' }],
    ['last_12_months', { from: '2025-08-01', to: '2026-07-25' }],
    ['last_24_months', { from: '2024-08-01', to: '2026-07-25' }],
    ['all', { from: '2022-03-04', to: '2026-07-25' }]
  ] as const)('resolves %s without including a future partial period', (value, expected) => {
    expect(resolveAskRange(
      { kind: 'preset', value },
      '2026-07-25',
      '2022-03-04'
    )).toEqual(expected);
  });

  it('resolves bounded rolling and absolute ranges inclusively', () => {
    expect(resolveAskRange(
      { kind: 'rolling_days', days: 30 },
      '2026-07-25'
    )).toEqual({ from: '2026-06-26', to: '2026-07-25' });
    expect(resolveAskRange(
      { kind: 'absolute', from: '2024-02-29', to: '2024-03-02' },
      '2026-07-25'
    )).toEqual({ from: '2024-02-29', to: '2024-03-02' });
  });

  it('uses the immediately preceding equal-length range', () => {
    expect(comparisonRange(
      { from: '2026-07-01', to: '2026-07-25' },
      'previous_period'
    )).toEqual({ from: '2026-06-06', to: '2026-06-30' });
    expect(comparisonRange(
      { from: '2024-02-29', to: '2024-03-31' },
      'previous_year'
    )).toEqual({ from: '2023-02-28', to: '2023-03-31' });
    expect(comparisonRange(
      { from: '2026-07-01', to: '2026-07-25' },
      'none'
    )).toBeNull();
  });
});

describe('Ask timezone handling', () => {
  it('uses a valid IANA timezone at UTC date boundaries', () => {
    const now = new Date('2026-07-24T22:30:00.000Z');
    expect(validatedTimeZone('Africa/Dar_es_Salaam')).toBe('Africa/Dar_es_Salaam');
    expect(dateInTimeZone(now, 'Africa/Dar_es_Salaam')).toBe('2026-07-25');
    expect(dateInTimeZone(now, 'America/Toronto')).toBe('2026-07-24');
  });

  it('falls back to UTC for absent or invalid zones', () => {
    expect(validatedTimeZone()).toBe('UTC');
    expect(validatedTimeZone('Not/A_TimeZone')).toBe('UTC');
    expect(dateInTimeZone(new Date('2026-07-24T23:59:59.000Z'), 'UTC')).toBe('2026-07-24');
  });
});
