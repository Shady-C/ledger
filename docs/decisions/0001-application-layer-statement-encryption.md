# ADR-0001: Encrypt Raw Statements in the Application Layer

**Date:** 2026-07-24
**Status:** Accepted
**Jira:** N/A

## Context

Ledger promises that raw financial statements are encrypted at rest. MinIO's
managed server-side encryption requires an external KMS/KES deployment, which
would add another stateful service and key-management topology to the Phase 0
local stack. Depending only on host-disk encryption would make the guarantee
environment-dependent and easy to misconfigure.

## Decision

The web service encrypts every validated statement before object storage using
AES-256-GCM and a 32-byte key supplied through `STATEMENT_ENCRYPTION_KEY`. The
versioned binary envelope is:

`LEDGER01 || 12-byte nonce || 16-byte authentication tag || ciphertext`

`LEDGER01` is also authenticated as additional data. The worker authenticates
and decrypts the envelope only after reading it from object storage. Plaintext
statement bytes and original filenames are never stored in MinIO. Object keys
use a per-account SHA-256 content digest plus the validated source extension,
which also makes repeat uploads idempotent.

## Alternatives Considered

- MinIO SSE-S3 with KES/KMS: strong and operationally mature, but adds a key
  service and deployment/backup design beyond the four-service Phase 0 stack.
- Host full-disk encryption only: useful defense in depth, but not portable or
  enforceable by Ledger.
- Unencrypted local objects: simplest, but contradicts the security design for
  highly sensitive financial files.

## Consequences

- Web and worker must share the same 64-hex-character key value.
- Losing or changing the key without a migration makes existing raw statements
  unreadable; production operators must back it up and manage it as a secret.
- Every encryption uses a fresh random nonce; authenticated corruption or a
  wrong key fails closed.
- A future key-rotation mechanism must decrypt and re-encrypt stored envelopes,
  or introduce an envelope-key registry.
- MinIO bucket-scoped credentials and host/storage encryption remain useful
  additional controls.
