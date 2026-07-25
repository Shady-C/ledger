import { describe, expect, it } from 'vitest';

import {
  mapTransactionRow,
  transactionConversionIndicators,
  transactionExplicitFeeEvidence,
  type TransactionRow
} from './transactions.js';

const row: TransactionRow = {
  id: 'e1bb45a1-04fd-4b64-a95b-f39714e8b522',
  account_id: '57e68f0d-846d-4f0e-858b-2838992d2bab',
  account_name: 'TZS wallet',
  booked_date: '2026-07-20',
  posted_date: '2026-07-21',
  description_raw: 'Merchant',
  merchant_name: 'Merchant',
  category_id: null,
  category_name: null,
  category_source: 'fallback',
  category_confidence: null,
  amount_native: '-25000.00',
  currency_native: 'TZS',
  original_amount: null,
  original_currency: null,
  amount_base: '-13.50',
  currency_base: 'CAD',
  fx_rate: '0.00054000',
  fx_rate_date: '2026-07-20',
  fx_fee_amount_native: null,
  is_fx_fee: false,
  direction: 'debit',
  enrichment: {},
  running_balance: '100000.00',
  running_balance_native: '100000.00',
  running_balance_base: '54.00'
};

describe('transaction conversion indicators', () => {
  it('marks reporting-only valuation as Converted', () => {
    expect(transactionConversionIndicators(row)).toEqual(['converted']);
  });

  it('allows FX and Pending to appear together', () => {
    expect(transactionConversionIndicators({
      ...row,
      original_amount: '-10.00',
      original_currency: 'USD',
      amount_base: null,
      fx_rate: null,
      fx_rate_date: null,
      running_balance_base: null
    })).toEqual(['fx', 'pending']);
  });

  it('shows no indicator when posted and reporting currency are identical', () => {
    const native = mapTransactionRow({
      ...row,
      amount_native: '-25.00',
      currency_native: 'CAD',
      amount_base: '-25.00',
      fx_rate: '1.00000000',
      running_balance: '100.00',
      running_balance_native: '100.00',
      running_balance_base: '100.00'
    });

    expect(native.conversionIndicators).toEqual([]);
    expect(native.valuationStatus).toBe('valued');
  });

  it('does not expose a reporting zero when no explicit fee was supplied', () => {
    expect(transactionExplicitFeeEvidence(row, {
      explicit_fee_native: '0.00',
      explicit_fee_base: '0.00'
    })).toEqual({
      explicitFeeNative: null,
      explicitFeeBase: null
    });
  });

  it('keeps native and reporting fee evidence together when a fee exists', () => {
    expect(transactionExplicitFeeEvidence({
      ...row,
      fx_fee_amount_native: '500.00'
    }, {
      explicit_fee_native: '500.00',
      explicit_fee_base: '0.27'
    })).toEqual({
      explicitFeeNative: '500.00',
      explicitFeeBase: '0.27'
    });
  });
});
