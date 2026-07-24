import { describe, expect, it } from 'vitest';

import { checkUploads } from './upload.js';

describe('Phase 1 OFX/QFX uploads', () => {
  it.each([
    ['statement.ofx', 'OFXHEADER:100\nDATA:OFXSGML\n<OFX><BANKMSGSRSV1>'],
    ['statement.qfx', '<?xml version="1.0"?><OFX><CREDITCARDMSGSRSV1>']
  ])('accepts a structurally recognizable %s file', async (name, content) => {
    const result = await checkUploads([new File([content], name)]);
    expect(result.ok).toBe(true);
  });

  it('rejects an arbitrary text file renamed as OFX', async () => {
    const result = await checkUploads([new File(['not a financial document'], 'statement.ofx')]);
    expect(result).toMatchObject({ ok: false });
  });
});
