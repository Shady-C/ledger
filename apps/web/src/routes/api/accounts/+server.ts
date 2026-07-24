import { json } from '@sveltejs/kit';

import { privateReadHeaders, unavailableOrInternal } from '$lib/server/api.js';
import { accountsSummarySql, query } from '$lib/server/db.js';

type AccountRow = {
  id: string;
  display_name: string;
  institution_name: string | null;
  kind: 'credit_card' | 'chequing' | 'savings' | 'wallet';
  native_currency: string;
  account_ref_masked: string | null;
  current_balance: string;
  last_statement_date: string | null;
};

export async function GET() {
  try {
    const result = await query<AccountRow>(accountsSummarySql);

    return json(
      {
        accounts: result.rows.map((row) => ({
          id: row.id,
          displayName: row.display_name,
          institutionName: row.institution_name,
          kind: row.kind,
          nativeCurrency: row.native_currency,
          accountRefMasked: row.account_ref_masked,
          currentBalance: row.current_balance,
          lastStatementDate: row.last_statement_date
        }))
      },
      { headers: privateReadHeaders }
    );
  } catch (error) {
    return unavailableOrInternal(error, 'accounts');
  }
}
