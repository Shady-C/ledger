import { json } from '@sveltejs/kit';
import { transactionQuerySchema } from '@ledger/shared-types';

import {
  privateReadHeaders,
  unavailableOrInternal,
  validationError
} from '$lib/server/api.js';
import { buildTransactionQueries, query } from '$lib/server/db.js';

type TransactionRow = {
  id: string;
  account_id: string;
  account_name: string;
  booked_date: string;
  posted_date: string | null;
  description_raw: string;
  merchant_name: string | null;
  category_id: string | null;
  category_name: string | null;
  amount_native: string;
  currency_native: string;
  amount_base: string;
  currency_base: string;
  fx_rate: string;
  direction: 'debit' | 'credit' | 'payment' | 'fee' | 'refund' | 'interest';
  enrichment: Record<string, unknown> | null;
  running_balance: string;
};
type CountRow = { total: number };

export async function GET({ url }) {
  const parsed = transactionQuerySchema.safeParse(Object.fromEntries(url.searchParams));
  if (!parsed.success) return validationError(parsed.error);

  try {
    const built = buildTransactionQueries(parsed.data);
    const [data, count] = await Promise.all([
      query<TransactionRow>(built.data.text, built.data.values),
      query<CountRow>(built.count.text, built.count.values)
    ]);
    const total = count.rows[0]?.total ?? 0;
    return json(
      {
        items: data.rows.map((row) => ({
          id: row.id,
          accountId: row.account_id,
          accountName: row.account_name,
          bookedDate: row.booked_date,
          postedDate: row.posted_date,
          description: row.description_raw,
          merchantName: row.merchant_name,
          categoryId: row.category_id,
          categoryName: row.category_name,
          amountNative: row.amount_native,
          currencyNative: row.currency_native,
          amountBase: row.amount_base,
          currencyBase: row.currency_base,
          fxRate: row.fx_rate,
          direction: row.direction,
          runningBalance: row.running_balance,
          enrichment: row.enrichment ?? {}
        })),
        page: parsed.data.page,
        pageSize: parsed.data.pageSize,
        total,
        totalPages: total === 0 ? 0 : Math.ceil(total / parsed.data.pageSize)
      },
      { headers: privateReadHeaders }
    );
  } catch (error) {
    return unavailableOrInternal(error, 'transactions');
  }
}
