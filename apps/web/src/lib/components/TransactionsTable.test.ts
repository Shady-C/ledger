/** @vitest-environment jsdom */

import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';

import TransactionsTable from './TransactionsTable.svelte';
import type { TransactionView } from './phase1-types.js';

afterEach(cleanup);

const common: Omit<TransactionView, 'id' | 'description' | 'amountNative' | 'currencyNative' | 'originalAmount' | 'originalCurrency' | 'amountBase' | 'fxRate' | 'fxRateDate' | 'fxFeeAmountNative' | 'isFxFee' | 'valuationStatus' | 'runningBalance' | 'runningBalanceNative' | 'runningBalanceBase'> = {
  accountId: '22222222-2222-4222-8222-222222222222',
  accountName: 'Travel account',
  bookedDate: '2026-07-19',
  postedDate: null,
  merchantName: null,
  categoryId: null,
  categoryName: null,
  categorySource: 'fallback',
  categoryConfidence: '0.0000',
  currencyBase: 'CAD',
  direction: 'debit',
  enrichment: {}
};

function transaction(overrides: Partial<TransactionView> & Pick<TransactionView, 'id' | 'description' | 'amountNative' | 'currencyNative'>): TransactionView {
  return {
    ...common,
    originalAmount: null,
    originalCurrency: null,
    amountBase: overrides.amountNative,
    fxRate: '1.00000000',
    fxRateDate: '2026-07-19',
    fxFeeAmountNative: null,
    isFxFee: false,
    valuationStatus: 'valued',
    runningBalance: overrides.amountNative,
    runningBalanceNative: overrides.amountNative,
    runningBalanceBase: overrides.amountNative,
    ...overrides
  };
}

describe('TransactionsTable amount stack', () => {
  it('shows three monetary layers, suppresses duplicates, and explains pending CAD values', () => {
    const items = [
      transaction({
        id: '55555555-5555-4555-8555-555555555551',
        description: 'USD purchase posted in Tanzania',
        amountNative: '-270000.00',
        currencyNative: 'TZS',
        originalAmount: '-100.00',
        originalCurrency: 'USD',
        amountBase: '-142.90',
        fxRate: '0.00052926',
        fxFeeAmountNative: '5000.00',
        runningBalance: '730000.00',
        runningBalanceNative: '730000.00',
        runningBalanceBase: '386.00'
      }),
      transaction({
        id: '55555555-5555-4555-8555-555555555552',
        description: 'Native CAD activity',
        amountNative: '-25.00',
        currencyNative: 'CAD',
        originalAmount: '-25.00',
        originalCurrency: 'CAD'
      }),
      transaction({
        id: '55555555-5555-4555-8555-555555555553',
        description: 'Pending USD valuation',
        amountNative: '-40.00',
        currencyNative: 'USD',
        amountBase: null,
        fxRate: null,
        fxRateDate: null,
        valuationStatus: 'pending_fx',
        runningBalance: '960.00',
        runningBalanceNative: '960.00',
        runningBalanceBase: null
      })
    ];

    render(TransactionsTable, {
      props: {
        data: { items, page: 1, pageSize: 25, total: 3, totalPages: 1 },
        accounts: [],
        categories: []
      }
    });

    expect(screen.getAllByText('Original')).toHaveLength(1);
    expect(screen.getAllByText('Posted')).toHaveLength(3);
    expect(screen.getAllByText('Reporting')).toHaveLength(2);
    expect(screen.getByText('CAD valuation pending')).toBeTruthy();
    expect(screen.getByText('Actual FX fee')).toBeTruthy();
  });
});
