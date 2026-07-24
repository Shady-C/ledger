import { json } from '@sveltejs/kit';

import { privateReadHeaders, unavailableOrInternal } from '$lib/server/api.js';
import { query, transactionFlowSql } from '$lib/server/db.js';

type UnresolvedRow = {
  merchant_id: string;
  merchant_name: string;
  flow_type: 'spend' | 'income' | 'transfer' | 'refund' | 'fee';
  transaction_count: number;
  first_seen: string;
  last_seen: string;
};

export async function GET() {
  try {
    const result = await query<UnresolvedRow>(`
      WITH classified AS (
        SELECT
          t.merchant_id,
          m.canonical_name AS merchant_name,
          ${transactionFlowSql('t', 'a')} AS flow_type,
          t.booked_date
        FROM txn t
        JOIN account a ON a.id = t.account_id
        JOIN merchant m ON m.id = t.merchant_id
        WHERE t.category_source = 'fallback'
      )
      SELECT
        merchant_id::text,
        merchant_name,
        flow_type,
        COUNT(*)::int AS transaction_count,
        MIN(booked_date)::text AS first_seen,
        MAX(booked_date)::text AS last_seen
      FROM classified
      GROUP BY merchant_id, merchant_name, flow_type
      ORDER BY transaction_count DESC, last_seen DESC, merchant_name, flow_type
    `);
    return json(
      {
        unresolved: result.rows.map((row) => ({
          merchantId: row.merchant_id,
          merchantName: row.merchant_name,
          flowType: row.flow_type,
          transactionCount: row.transaction_count,
          firstSeen: row.first_seen,
          lastSeen: row.last_seen
        }))
      },
      { headers: privateReadHeaders }
    );
  } catch (error) {
    return unavailableOrInternal(error, 'unresolved merchants');
  }
}
