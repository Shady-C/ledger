import { describe, expect, it } from 'vitest';

import { statementObjectKey } from './storage.js';

describe('statementObjectKey', () => {
  it('uses the plaintext SHA-256 digest, account, and normalized source extension', () => {
    const first = statementObjectKey({
      accountId: 'account-a',
      fileName: 'Private Original Name.CSV',
      body: Buffer.from('same statement bytes')
    });
    const second = statementObjectKey({
      accountId: 'account-a',
      fileName: 'renamed.csv',
      body: Buffer.from('same statement bytes')
    });

    expect(first).toEqual(second);
    expect(first).toEqual({
      format: 'csv',
      key: 'statements/account-a/a61016a1ac022fcb97a91ee121649ba7c1455043075e6a92c76650644e4254a5.csv'
    });
    expect(first.key).not.toContain('Private');
  });

  it('preserves QFX format for worker adapter detection', () => {
    const result = statementObjectKey({
      accountId: 'account-a',
      fileName: 'statement.qfx',
      body: new TextEncoder().encode('<OFX></OFX>')
    });
    expect(result.format).toBe('qfx');
    expect(result.key).toMatch(/\.qfx$/);
  });

  it('changes across accounts and plaintext content', () => {
    const body = Buffer.from('statement');
    const first = statementObjectKey({ accountId: 'account-a', fileName: 'one.xlsx', body });
    const otherAccount = statementObjectKey({ accountId: 'account-b', fileName: 'one.xlsx', body });
    const otherContent = statementObjectKey({
      accountId: 'account-a',
      fileName: 'one.xlsx',
      body: Buffer.from('different')
    });
    expect(first.key).not.toBe(otherAccount.key);
    expect(first.key).not.toBe(otherContent.key);
  });
});
