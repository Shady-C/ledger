import { describe, expect, it } from 'vitest';

import { ConfigurationError, parseAskProviderMode, parseFxMaxStalenessDays } from './env.js';

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

describe('parseAskProviderMode', () => {
  it('defaults to live and accepts the supported modes', () => {
    expect(parseAskProviderMode(undefined)).toBe('live');
    expect(parseAskProviderMode('LIVE')).toBe('live');
    expect(parseAskProviderMode(' stub ')).toBe('stub');
  });

  it('rejects unknown provider modes', () => {
    expect(() => parseAskProviderMode('fixture')).toThrow(ConfigurationError);
  });
});
