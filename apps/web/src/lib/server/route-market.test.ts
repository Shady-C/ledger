import { describe, expect, it } from 'vitest';

import { GET as getInsightSettings } from '../../routes/api/insights/settings/+server.js';
import { GET as getTransactionDetail } from '../../routes/api/transactions/[id]/+server.js';

describe('market-aware read routes', () => {
  it('rejects an unsupported market on transaction detail before reading the ledger', async () => {
    const response = await getTransactionDetail({
      params: { id: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522' },
      url: new URL('http://ledger.test/api/transactions/e1bb45a1-04fd-4b64-a95b-f39714e8b522?market=US')
    } as Parameters<typeof getTransactionDetail>[0]);

    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ error: { code: 'invalid_request' } });
  });

  it('validates the optional market on the Insights settings read', async () => {
    const response = await getInsightSettings({
      url: new URL('http://ledger.test/api/insights/settings?market=US')
    } as Parameters<typeof getInsightSettings>[0]);

    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ error: { code: 'invalid_request' } });
  });
});
