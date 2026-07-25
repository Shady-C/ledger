import type { JobKind, JobStatus } from '@ledger/shared-types';

import { buildAccountsSummaryQuery, query } from './db.js';

export type AccountSummaryRow = {
  id: string;
  institution_id: string | null;
  display_name: string;
  institution_name: string | null;
  kind: 'credit_card' | 'chequing' | 'savings' | 'wallet';
  native_currency: string;
  market_code: 'CA' | 'TZ' | null;
  account_ref_masked: string | null;
  current_balance: string;
  current_balance_base: string | null;
  base_currency: string;
  balance_basis: 'balance' | 'net_activity';
  last_statement_date: string | null;
  credit_limit: string | null;
  used_credit: string | null;
  available_credit: string | null;
  utilization_percent: string | null;
};

export function mapAccountSummary(row: AccountSummaryRow) {
  return {
    id: row.id,
    institutionId: row.institution_id,
    displayName: row.display_name,
    institutionName: row.institution_name,
    kind: row.kind,
    nativeCurrency: row.native_currency,
    marketCode: row.market_code,
    accountRefMasked: row.account_ref_masked,
    currentBalance: row.current_balance,
    currentBalanceBase: row.current_balance_base,
    baseCurrency: row.base_currency,
    balanceBasis: row.balance_basis,
    lastStatementDate: row.last_statement_date,
    creditLimit: row.credit_limit,
    usedCredit: row.used_credit,
    availableCredit: row.available_credit,
    utilizationPercent: row.utilization_percent
  };
}

export async function readAccountSummary(id: string) {
  const built = buildAccountsSummaryQuery(id);
  const result = await query<AccountSummaryRow>(built.text, built.values);
  return result.rows[0] ? mapAccountSummary(result.rows[0]) : null;
}

type EnqueuedJobRow = { id: string; kind: JobKind; status: JobStatus };

export async function enqueueJob(
  kind: JobKind,
  payload: Record<string, unknown>,
  deduplicationKey: string
) {
  const result = await query<EnqueuedJobRow>(
    `INSERT INTO job (kind, payload, status, deduplication_key)
     VALUES ($1, $2::jsonb, 'queued', $3)
     ON CONFLICT (kind, deduplication_key)
       WHERE deduplication_key IS NOT NULL
         AND status IN ('queued', 'claimed')
     DO UPDATE SET updated_at = job.updated_at
     RETURNING id::text, kind, status`,
    [kind, JSON.stringify(payload), deduplicationKey]
  );
  const job = result.rows[0];
  if (!job) throw new Error('Job insert did not return a row');
  return { jobId: job.id, kind: job.kind, status: job.status as 'queued' | 'claimed' };
}

export function postgresErrorCode(error: unknown): string | null {
  if (typeof error !== 'object' || error === null || !('code' in error)) return null;
  const code = (error as { code?: unknown }).code;
  return typeof code === 'string' ? code : null;
}
