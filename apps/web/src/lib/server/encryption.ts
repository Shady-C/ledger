import {
  createCipheriv,
  createDecipheriv,
  randomBytes,
  timingSafeEqual
} from 'node:crypto';

export const statementEnvelopeMagic = Buffer.from('LEDGER01', 'ascii');
const nonceBytes = 12;
const tagBytes = 16;
const keyBytes = 32;

function assertKey(key: Uint8Array) {
  if (key.byteLength !== keyBytes) throw new Error('Statement encryption requires a 32-byte key.');
}

export function encryptStatementBytes(plaintext: Uint8Array, key: Uint8Array) {
  assertKey(key);
  const nonce = randomBytes(nonceBytes);
  const cipher = createCipheriv('aes-256-gcm', key, nonce);
  cipher.setAAD(statementEnvelopeMagic);
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([statementEnvelopeMagic, nonce, tag, ciphertext]);
}

export function decryptStatementBytes(envelope: Uint8Array, key: Uint8Array) {
  assertKey(key);
  const bytes = Buffer.from(envelope);
  const minimumLength = statementEnvelopeMagic.byteLength + nonceBytes + tagBytes;
  if (bytes.byteLength < minimumLength) throw new Error('Invalid encrypted statement envelope.');

  const magic = bytes.subarray(0, statementEnvelopeMagic.byteLength);
  if (magic.byteLength !== statementEnvelopeMagic.byteLength || !timingSafeEqual(magic, statementEnvelopeMagic)) {
    throw new Error('Unsupported encrypted statement envelope.');
  }
  const nonceStart = statementEnvelopeMagic.byteLength;
  const tagStart = nonceStart + nonceBytes;
  const ciphertextStart = tagStart + tagBytes;
  const nonce = bytes.subarray(nonceStart, tagStart);
  const tag = bytes.subarray(tagStart, ciphertextStart);
  const ciphertext = bytes.subarray(ciphertextStart);

  const decipher = createDecipheriv('aes-256-gcm', key, nonce);
  decipher.setAAD(statementEnvelopeMagic);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ciphertext), decipher.final()]);
}
