import { json } from '@sveltejs/kit';
import { categorizationProposalStatusSchema } from '@ledger/shared-types';

import { apiError, privateReadHeaders, unavailableOrInternal } from '$lib/server/api.js';
import { query } from '$lib/server/db.js';

type ProposalRow = {
  id: string;
  opaque_key: string;
  merchant_id: string;
  merchant_name: string;
  flow_type: 'spend' | 'income' | 'transfer' | 'refund' | 'fee';
  proposed_category_id: string | null;
  proposed_category_name: string | null;
  proposed_category_kind: 'spend' | 'income' | 'transfer' | 'fee' | null;
  confidence: string;
  status: 'pending' | 'accepted' | 'rejected';
  provider: string;
  model: string;
  reviewed_at: Date | null;
  created_at: Date;
};

function publicProposal(row: ProposalRow) {
  return {
    id: row.id,
    opaqueKey: row.opaque_key,
    merchantId: row.merchant_id,
    merchantName: row.merchant_name,
    flowType: row.flow_type,
    proposedCategoryId: row.proposed_category_id,
    proposedCategoryName: row.proposed_category_name,
    proposedCategoryKind: row.proposed_category_kind,
    confidence: row.confidence,
    status: row.status,
    provider: row.provider,
    model: row.model,
    reviewedAt: row.reviewed_at?.toISOString() ?? null,
    createdAt: row.created_at.toISOString()
  };
}

const proposalSelectSql = `
  SELECT
    proposal.id::text,
    proposal.opaque_key::text,
    proposal.merchant_id::text,
    merchant.canonical_name AS merchant_name,
    proposal.flow_type,
    proposal.proposed_category_id::text,
    COALESCE(category.name, proposal.proposed_category_name) AS proposed_category_name,
    COALESCE(category.kind, proposal.proposed_category_kind) AS proposed_category_kind,
    proposal.confidence::text,
    proposal.status,
    proposal.provider,
    proposal.model,
    proposal.reviewed_at,
    proposal.created_at
  FROM categorization_proposal proposal
  JOIN merchant ON merchant.id = proposal.merchant_id
  LEFT JOIN category ON category.id = proposal.proposed_category_id`;

export async function GET({ url }) {
  const rawStatus = url.searchParams.get('status') ?? 'pending';
  const status = rawStatus === 'all' ? 'all' : categorizationProposalStatusSchema.safeParse(rawStatus);
  if (status !== 'all' && !status.success) {
    return apiError(400, 'invalid_status', 'The proposal status filter is invalid.');
  }

  try {
    const result = await query<ProposalRow>(
      `${proposalSelectSql}
       ${status === 'all' ? '' : 'WHERE proposal.status = $1'}
       ORDER BY proposal.created_at, proposal.id`,
      status === 'all' ? [] : [status.data]
    );
    return json({ proposals: result.rows.map(publicProposal) }, { headers: privateReadHeaders });
  } catch (error) {
    return unavailableOrInternal(error, 'categorization proposals');
  }
}
