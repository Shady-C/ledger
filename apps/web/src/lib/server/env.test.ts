import { describe, expect, it } from 'vitest';

import { ConfigurationError, parseFxMaxStalenessDays } from './env.js';

describe('parseFxMaxStalenessDays', () => {
  it('defaults to seven days and accepts the inclusive configured range', () => {
    expect(parseFxMaxStalenessDays(undefined)).toBe(7);
    expect(parseFxMaxStalenessDays('0')).toBe(0);
    expect(parseFxMaxStalenessDays('7')).toBe(7);
  });

  it.each(['-1', '8', '1.5', 'not-a-number'])('rejects an unsafe value: %s', (value) => {
    expect(() => parseFxMaxStalenessDays(value)).toThrow(ConfigurationError);
  });
});
