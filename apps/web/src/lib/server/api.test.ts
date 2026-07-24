import { describe, expect, it } from 'vitest';

import { privateReadHeaders } from './api.js';

describe('privateReadHeaders', () => {
  it('prevents stale financial summaries after an import', () => {
    expect(privateReadHeaders['cache-control']).toBe('no-store');
  });
});
