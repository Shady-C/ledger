import type { ConversionIndicator } from '@ledger/shared-types';

export type TransactionRow = {
  id: string;
  account_id: string;
  account_name: string;
  booked_date: string;
  posted_date: string | null;
  description_raw: string;
  merchant_name: string | null;
  category_id: string | null;
  category_name: string | null;
  category_source: 'fallback' | 'rule' | 'ai' | 'user_merchant' | 'user_transaction';
  category_confidence: string | null;
  amount_native: string;
  currency_native: string;
  original_amount: string | null;
  original_currency: string | null;
  amount_base: string | null;
  currency_base: string;
  fx_rate: string | null;
  fx_rate_date: string | null;
  fx_fee_amount_native: string | null;
  is_fx_fee: boolean;
  direction: 'debit' | 'credit' | 'payment' | 'fee' | 'refund' | 'interest';
  enrichment: Record<string, unknown> | null;
  running_balance: string;
  running_balance_native: string;
  running_balance_base: string | null;
};

export function transactionConversionIndicators(row: TransactionRow): ConversionIndicator[] {
  const indicators: ConversionIndicator[] = [];
  const originalDiffers = row.original_amount !== null
    && row.original_currency !== null
    && (row.original_currency !== row.currency_native || row.original_amount !== row.amount_native);
  if (originalDiffers || row.fx_fee_amount_native !== null || row.is_fx_fee) {
    indicators.push('fx');
  }
  if (row.amount_base === null) {
    indicators.push('pending');
  } else if (!indicators.includes('fx') && row.currency_native !== row.currency_base) {
    indicators.push('converted');
  }
  return indicators;
}

export function transactionExplicitFeeEvidence(
  row: Pick<TransactionRow, 'fx_fee_amount_native' | 'is_fx_fee'>,
  evidence: { explicit_fee_native: string; explicit_fee_base: string | null } | undefined
) {
  if (!row.is_fx_fee && row.fx_fee_amount_native === null) {
    return { explicitFeeNative: null, explicitFeeBase: null };
  }
  return {
    explicitFeeNative: evidence?.explicit_fee_native ?? null,
    explicitFeeBase: evidence?.explicit_fee_base ?? null
  };
}

export function mapTransactionRow(row: TransactionRow) {
  return {
    id: row.id,
    accountId: row.account_id,
    accountName: row.account_name,
    bookedDate: row.booked_date,
    postedDate: row.posted_date,
    description: row.description_raw,
    merchantName: row.merchant_name,
    categoryId: row.category_id,
    categoryName: row.category_name,
    categorySource: row.category_source,
    categoryConfidence: row.category_confidence,
    amountNative: row.amount_native,
    currencyNative: row.currency_native,
    originalAmount: row.original_amount,
    originalCurrency: row.original_currency,
    amountBase: row.amount_base,
    currencyBase: row.currency_base,
    fxRate: row.fx_rate,
    fxRateDate: row.fx_rate_date,
    fxFeeAmountNative: row.fx_fee_amount_native,
    isFxFee: row.is_fx_fee,
    valuationStatus: row.amount_base == null ? 'pending_fx' as const : 'valued' as const,
    conversionIndicators: transactionConversionIndicators(row),
    direction: row.direction,
    runningBalance: row.running_balance,
    runningBalanceNative: row.running_balance_native,
    runningBalanceBase: row.running_balance_base,
    enrichment: row.enrichment ?? {}
  };
}
