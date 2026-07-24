export class ConfigurationError extends Error {
  constructor(variable: string, problem = 'is missing') {
    super(`Invalid service configuration: ${variable} ${problem}`);
    this.name = 'ConfigurationError';
  }
}

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new ConfigurationError(name);
  return value;
}

function integer(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value > 0 ? value : fallback;
}

function boolean(name: string, fallback: boolean) {
  const raw = process.env[name]?.trim().toLowerCase();
  if (!raw) return fallback;
  if (raw === 'true') return true;
  if (raw === 'false') return false;
  return fallback;
}

export function databaseConfig() {
  return {
    connectionString: required('DATABASE_URL'),
    max: integer('DATABASE_POOL_SIZE', 10),
    statement_timeout: integer('DATABASE_STATEMENT_TIMEOUT_MS', 10_000)
  };
}

export function objectStorageConfig() {
  const endpoint = new URL(required('S3_ENDPOINT'));
  return {
    endpoint: endpoint.toString(),
    region: process.env.S3_REGION?.trim() || 'us-east-1',
    bucket: process.env.S3_BUCKET?.trim() || 'ledger-statements',
    accessKeyId: required('S3_ACCESS_KEY'),
    secretAccessKey: required('S3_SECRET_KEY'),
    forcePathStyle: boolean('S3_FORCE_PATH_STYLE', true)
  };
}

export function uploadLimits() {
  return {
    maxFiles: integer('UPLOAD_MAX_FILES', 10),
    maxFileBytes: integer('UPLOAD_MAX_FILE_BYTES', 15 * 1024 * 1024),
    maxTotalBytes: integer('UPLOAD_MAX_TOTAL_BYTES', 40 * 1024 * 1024)
  };
}

export function parseFxMaxStalenessDays(value: string | undefined): number {
  const raw = value?.trim();
  if (!raw) return 7;
  const days = Number(raw);
  if (!Number.isSafeInteger(days) || days < 0 || days > 7) {
    throw new ConfigurationError('FX_MAX_STALENESS_DAYS', 'must be an integer from 0 through 7');
  }
  return days;
}

export function fxMaxStalenessDays(): number {
  return parseFxMaxStalenessDays(process.env.FX_MAX_STALENESS_DAYS);
}

export function parseStatementEncryptionKey(value: string | undefined) {
  if (!value || !/^[0-9a-fA-F]{64}$/.test(value)) {
    throw new ConfigurationError('STATEMENT_ENCRYPTION_KEY', 'must be exactly 64 hexadecimal characters');
  }
  return Buffer.from(value, 'hex');
}

export function statementEncryptionKey() {
  return parseStatementEncryptionKey(process.env.STATEMENT_ENCRYPTION_KEY?.trim());
}
