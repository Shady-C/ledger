import { describe, expect, it } from 'vitest';

import { parseStatementEncryptionKey } from './env.js';
import {
  decryptStatementBytes,
  encryptStatementBytes,
  statementEnvelopeMagic
} from './encryption.js';

describe('statement encryption envelope', () => {
  const key = Buffer.from('11'.repeat(32), 'hex');

  it('round-trips bytes with the versioned magic prefix', () => {
    const plaintext = Buffer.from('Date,Description,Amount\n2026-01-01,Coffee,4.25\n');
    const encrypted = encryptStatementBytes(plaintext, key);

    expect(encrypted.subarray(0, 8)).toEqual(statementEnvelopeMagic);
    expect(encrypted).toHaveLength(plaintext.length + 8 + 12 + 16);
    expect(encrypted.includes(plaintext)).toBe(false);
    expect(decryptStatementBytes(encrypted, key)).toEqual(plaintext);
  });

  it('rejects an envelope whose authenticated ciphertext was changed', () => {
    const encrypted = encryptStatementBytes(Buffer.from('private statement'), key);
    encrypted[encrypted.length - 1] ^= 1;
    expect(() => decryptStatementBytes(encrypted, key)).toThrow();
  });

  it('uses a fresh nonce for repeated encryption', () => {
    const plaintext = Buffer.from('same bytes');
    expect(encryptStatementBytes(plaintext, key)).not.toEqual(encryptStatementBytes(plaintext, key));
  });
});

describe('parseStatementEncryptionKey', () => {
  it('accepts exactly 32 bytes encoded as hex', () => {
    expect(parseStatementEncryptionKey('ab'.repeat(32))).toHaveLength(32);
  });

  it.each(['', 'ab', 'z1'.repeat(32), 'ab'.repeat(33)])('rejects invalid key value %j', (value) => {
    expect(() => parseStatementEncryptionKey(value)).toThrow(/64 hexadecimal characters/);
  });
});
