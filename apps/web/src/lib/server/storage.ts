import {
  CreateBucketCommand,
  HeadBucketCommand,
  PutObjectCommand,
  S3Client
} from '@aws-sdk/client-s3';
import { createHash } from 'node:crypto';

import { encryptStatementBytes } from './encryption.js';
import { objectStorageConfig, statementEncryptionKey } from './env.js';

let client: S3Client | undefined;
let bucketReady: Promise<void> | undefined;

function storage() {
  const config = objectStorageConfig();
  if (!client) {
    client = new S3Client({
      endpoint: config.endpoint,
      region: config.region,
      forcePathStyle: config.forcePathStyle,
      credentials: {
        accessKeyId: config.accessKeyId,
        secretAccessKey: config.secretAccessKey
      }
    });
  }
  return { client, bucket: config.bucket };
}

function isPreconditionFailed(error: unknown) {
  if (typeof error !== 'object' || error === null) return false;
  const candidate = error as { name?: string; $metadata?: { httpStatusCode?: number } };
  return candidate.name === 'PreconditionFailed' || candidate.$metadata?.httpStatusCode === 412;
}

async function ensureBucket() {
  if (!bucketReady) {
    bucketReady = (async () => {
      const { client: s3, bucket } = storage();
      try {
        await s3.send(new HeadBucketCommand({ Bucket: bucket }));
      } catch {
        try {
          await s3.send(new CreateBucketCommand({ Bucket: bucket }));
        } catch (error) {
          bucketReady = undefined;
          throw error;
        }
      }
    })();
  }
  return bucketReady;
}

function sourceFormat(name: string) {
  const extension = name.toLowerCase().split('.').pop();
  if (!extension || !['csv', 'xlsx', 'pdf', 'ofx', 'qfx'].includes(extension)) {
    throw new Error('Unsupported statement format.');
  }
  return extension;
}

export function statementObjectKey(input: {
  accountId: string;
  fileName: string;
  body: Uint8Array;
}) {
  const format = sourceFormat(input.fileName);
  const digest = createHash('sha256').update(input.body).digest('hex');
  return {
    format,
    key: `statements/${input.accountId}/${digest}.${format}`
  };
}

export async function storeStatement(input: {
  accountId: string;
  fileName: string;
  body: Uint8Array;
}) {
  await ensureBucket();
  const { client: s3, bucket } = storage();
  const { format, key } = statementObjectKey(input);
  const encrypted = encryptStatementBytes(input.body, statementEncryptionKey());
  try {
    await s3.send(
      new PutObjectCommand({
        Bucket: bucket,
        Key: key,
        Body: encrypted,
        ContentLength: encrypted.byteLength,
        ContentType: 'application/octet-stream',
        IfNoneMatch: '*',
        Metadata: {
          encryption_format: 'ledger-aes-256-gcm-v1',
          source_format: format
        }
      })
    );
    return { key, created: true };
  } catch (error) {
    if (isPreconditionFailed(error)) return { key, created: false };
    throw error;
  }
}
