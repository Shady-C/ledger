/** @vitest-environment jsdom */

import { cleanup, render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import CategoryCell from './CategoryCell.svelte';
import type { CategoryView, TransactionView } from './phase1-types.js';

afterEach(cleanup);

const diningId = '33333333-3333-4333-8333-333333333333';
const otherId = '44444444-4444-4444-8444-444444444444';
const transactionId = '55555555-5555-4555-8555-555555555555';

const categories: CategoryView[] = [
  { id: diningId, parentId: null, name: 'Dining', kind: 'spend', archivedAt: null, isProtected: false },
  { id: otherId, parentId: null, name: 'Other', kind: 'spend', archivedAt: null, isProtected: true }
];

const transaction: TransactionView = {
  id: transactionId,
  accountId: '22222222-2222-4222-8222-222222222222',
  accountName: 'Travel rewards',
  bookedDate: '2026-07-19',
  postedDate: '2026-07-20',
  description: 'COFFEE HOUSE 1842',
  merchantName: 'Coffee House',
  categoryId: diningId,
  categoryName: 'Dining',
  categorySource: 'ai',
  categoryConfidence: '0.92',
  amountNative: '12.40',
  currencyNative: 'CAD',
  originalAmount: null,
  originalCurrency: null,
  amountBase: '12.40',
  currencyBase: 'CAD',
  fxRate: '1.00',
  fxRateDate: '2026-07-19',
  fxFeeAmountNative: null,
  isFxFee: false,
  valuationStatus: 'valued',
  direction: 'debit',
  runningBalance: '1200.00',
  runningBalanceNative: '1200.00',
  runningBalanceBase: '1200.00',
  enrichment: {}
};

describe('CategoryCell', () => {
  it('keeps one-transaction correction as the default explicit action', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn(async () => undefined);
    render(CategoryCell, { props: { transaction, categories, onSave } });

    await user.click(screen.getByRole('button', { name: /Change category for Coffee House/ }));
    await user.selectOptions(screen.getByLabelText('New category'), otherId);
    await user.click(screen.getByRole('button', { name: 'This transaction' }));

    expect(onSave).toHaveBeenCalledWith(transactionId, otherId, false);
  });

  it('only learns a merchant mapping through the separate merchant action', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn(async () => undefined);
    render(CategoryCell, { props: { transaction, categories, onSave } });

    await user.click(screen.getByRole('button', { name: /Change category for Coffee House/ }));
    await user.selectOptions(screen.getByLabelText('New category'), otherId);
    await user.click(screen.getByRole('button', { name: 'Matching merchant' }));

    expect(onSave).toHaveBeenCalledWith(transactionId, otherId, true);
  });
});
