import pg from 'pg';
import type { QueryResultRow } from 'pg';
import type { AnalyticsQuery, MarketCode, TransactionQuery } from '@ledger/shared-types';

import { databaseConfig, fxMaxStalenessDays } from './env.js';

const { Pool } = pg;
const FX_MAX_STALENESS_DAYS = fxMaxStalenessDays();
let pool: pg.Pool | undefined;

export function getPool(): pg.Pool {
  if (!pool) pool = new Pool(databaseConfig());
  return pool;
}

export function query<T extends QueryResultRow>(text: string, values: readonly unknown[] = []) {
  return getPool().query<T>(text, [...values]);
}

type BuiltQuery = { text: string; values: unknown[] };

export function buildAccountsSummaryQuery(accountId?: string, market?: MarketCode): BuiltQuery {
  const values: unknown[] = [];
  const conditions: string[] = [];
  if (accountId) conditions.push(`a.id = ${addValue(values, accountId)}::uuid`);
  if (market) conditions.push(`a.market_code = ${addValue(values, market)}`);
  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
  return {
    text: `
      WITH setting AS (
        SELECT base_currency
        FROM ledger_settings
        WHERE singleton
      ), positions AS (
        SELECT
          a.id,
          a.institution_id,
          a.display_name,
          i.name AS institution_name,
          a.kind,
          a.native_currency,
          a.market_code,
          a.account_ref_masked,
          a.credit_limit,
          setting.base_currency,
          CASE
            WHEN latest.closing_balance IS NOT NULL
              AND latest.reconcile_status IN ('ok', 'gap', 'pending') THEN
              latest.closing_balance + COALESCE(activity.after_latest, 0)
            ELSE
              COALESCE(earliest.opening_balance, 0) + COALESCE(activity.total, 0)
          END AS current_balance,
          CASE
            WHEN (
              latest.closing_balance IS NOT NULL
              AND latest.reconcile_status IN ('ok', 'gap', 'pending')
            ) OR (latest.closing_balance IS NULL AND earliest.opening_balance IS NOT NULL)
              THEN 'balance'
            ELSE 'net_activity'
          END AS balance_basis,
          latest.period_end AS last_statement_date
        FROM account a
        CROSS JOIN setting
        LEFT JOIN institution i ON i.id = a.institution_id
        LEFT JOIN LATERAL (
          SELECT s.period_end, s.closing_balance, s.reconcile_status
          FROM statement s
          WHERE s.account_id = a.id
            AND s.closing_balance IS NOT NULL
          ORDER BY s.period_end DESC, s.id DESC
          LIMIT 1
        ) latest ON true
        LEFT JOIN LATERAL (
          SELECT s.opening_balance
          FROM statement s
          WHERE s.account_id = a.id
            AND s.opening_balance IS NOT NULL
            AND s.reconcile_status IN ('ok', 'gap', 'pending')
          ORDER BY s.period_start, s.id
          LIMIT 1
        ) earliest ON true
        LEFT JOIN LATERAL (
          SELECT
            COALESCE(SUM(t.amount_native), 0) AS total,
            COALESCE(
              SUM(t.amount_native) FILTER (
                WHERE COALESCE(t.posted_date, t.booked_date) > latest.period_end
              ),
              0
            ) AS after_latest
          FROM txn t
          WHERE t.account_id = a.id
        ) activity ON true
        ${where}
      )
      SELECT
        positions.id,
        positions.institution_id,
        positions.display_name,
        positions.institution_name,
        positions.kind,
        positions.native_currency,
        positions.market_code,
        positions.account_ref_masked,
        positions.current_balance::text,
        CASE
          WHEN positions.native_currency = positions.base_currency
            THEN ROUND(positions.current_balance, 2)::text
          WHEN current_fx.rate IS NOT NULL
            THEN ROUND(positions.current_balance * current_fx.rate, 2)::text
          ELSE NULL
        END AS current_balance_base,
        positions.base_currency,
        positions.balance_basis,
        positions.last_statement_date::text,
        positions.credit_limit::text,
        CASE
          WHEN positions.kind = 'credit_card'
            AND positions.credit_limit IS NOT NULL
            AND positions.balance_basis = 'balance'
            THEN GREATEST(positions.current_balance, 0)::text
          ELSE NULL
        END AS used_credit,
        CASE
          WHEN positions.kind = 'credit_card'
            AND positions.credit_limit IS NOT NULL
            AND positions.balance_basis = 'balance'
            THEN (positions.credit_limit - positions.current_balance)::text
          ELSE NULL
        END AS available_credit,
        CASE
          WHEN positions.kind = 'credit_card'
            AND positions.credit_limit IS NOT NULL
            AND positions.balance_basis = 'balance'
            THEN ROUND(GREATEST(positions.current_balance, 0) / positions.credit_limit * 100, 2)::text
          ELSE NULL
        END AS utilization_percent
      FROM positions
      LEFT JOIN LATERAL (
        SELECT rate, as_of
        FROM fx_rate
        WHERE base = positions.native_currency
          AND quote = positions.base_currency
          AND as_of <= CURRENT_DATE
          AND as_of >= CURRENT_DATE - ${FX_MAX_STALENESS_DAYS}
        ORDER BY as_of DESC
        LIMIT 1
      ) current_fx ON positions.native_currency <> positions.base_currency
      ORDER BY positions.display_name`,
    values
  };
}

export const accountsSummarySql = buildAccountsSummaryQuery().text;

export function buildCreditUtilizationSummaryQuery(market?: MarketCode): BuiltQuery {
  const values: unknown[] = [];
  const marketWhere = market ? `AND a.market_code = ${addValue(values, market)}` : '';
  return { text: `
  WITH setting AS (
    SELECT base_currency
    FROM ledger_settings
    WHERE singleton
  ), positions AS (
    SELECT
      a.id AS account_id,
      a.display_name,
      a.native_currency,
      a.credit_limit,
      setting.base_currency,
      CASE
        WHEN latest.closing_balance IS NOT NULL
          AND latest.reconcile_status IN ('ok', 'gap', 'pending')
          THEN latest.closing_balance + COALESCE(activity.after_latest, 0)
        ELSE COALESCE(earliest.opening_balance, 0) + COALESCE(activity.total, 0)
      END AS current_balance,
      (
        latest.closing_balance IS NOT NULL
        AND latest.reconcile_status IN ('ok', 'gap', 'pending')
      ) OR (latest.closing_balance IS NULL AND earliest.opening_balance IS NOT NULL) AS verified
    FROM account a
    CROSS JOIN setting
    LEFT JOIN LATERAL (
      SELECT s.period_end, s.closing_balance, s.reconcile_status
      FROM statement s
      WHERE s.account_id = a.id
        AND s.closing_balance IS NOT NULL
      ORDER BY s.period_end DESC, s.id DESC
      LIMIT 1
    ) latest ON true
    LEFT JOIN LATERAL (
      SELECT s.opening_balance
      FROM statement s
      WHERE s.account_id = a.id
        AND s.opening_balance IS NOT NULL
        AND s.reconcile_status IN ('ok', 'gap', 'pending')
      ORDER BY s.period_start, s.id
      LIMIT 1
    ) earliest ON true
    LEFT JOIN LATERAL (
      SELECT
        COALESCE(SUM(t.amount_native), 0) AS total,
        COALESCE(
          SUM(t.amount_native) FILTER (
            WHERE COALESCE(t.posted_date, t.booked_date) > latest.period_end
          ),
          0
        ) AS after_latest
      FROM txn t
      WHERE t.account_id = a.id
    ) activity ON true
    WHERE a.kind = 'credit_card'
      ${marketWhere}
  ), valued AS (
    SELECT
      positions.*,
      CASE
        WHEN positions.native_currency = positions.base_currency THEN 1
        ELSE current_fx.rate
      END AS fx_rate
    FROM positions
    LEFT JOIN LATERAL (
      SELECT rate
      FROM fx_rate
      WHERE base = positions.native_currency
        AND quote = positions.base_currency
        AND as_of <= CURRENT_DATE
        AND as_of >= CURRENT_DATE - ${FX_MAX_STALENESS_DAYS}
      ORDER BY as_of DESC
      LIMIT 1
    ) current_fx ON positions.native_currency <> positions.base_currency
  ), evaluated AS (
    SELECT
      valued.*,
      CASE
        WHEN credit_limit IS NULL THEN 'missing_credit_limit'
        WHEN NOT verified THEN 'unverified_balance'
        WHEN fx_rate IS NULL THEN 'missing_fx_rate'
        ELSE NULL
      END AS excluded_reason
    FROM valued
  )
  SELECT
    setting.base_currency,
    COALESCE(
      SUM(ROUND(GREATEST(current_balance, 0) * fx_rate, 2))
        FILTER (WHERE excluded_reason IS NULL),
      0
    )::text AS used_credit_base,
    COALESCE(
      SUM(ROUND(credit_limit * fx_rate, 2)) FILTER (WHERE excluded_reason IS NULL),
      0
    )::text AS credit_limit_base,
    COALESCE(
      SUM(ROUND((credit_limit - current_balance) * fx_rate, 2))
        FILTER (WHERE excluded_reason IS NULL),
      0
    )::text AS available_credit_base,
    ROUND(
      SUM(GREATEST(current_balance, 0) * fx_rate)
        FILTER (WHERE excluded_reason IS NULL)
      / NULLIF(
          SUM(credit_limit * fx_rate) FILTER (WHERE excluded_reason IS NULL),
          0
        )
      * 100,
      2
    )::text AS utilization_percent,
    (COUNT(evaluated.account_id) FILTER (WHERE excluded_reason IS NULL))::int
      AS included_account_count,
    COALESCE(
      jsonb_agg(
        jsonb_build_object(
          'accountId', evaluated.account_id::text,
          'displayName', evaluated.display_name,
          'reason', evaluated.excluded_reason
        )
        ORDER BY evaluated.display_name, evaluated.account_id
      ) FILTER (WHERE excluded_reason IS NOT NULL),
      '[]'::jsonb
    ) AS excluded_accounts
  FROM setting
  LEFT JOIN evaluated ON true
  GROUP BY setting.base_currency
`, values };
}

export const creditUtilizationSummarySql = buildCreditUtilizationSummaryQuery().text;

const transactionSortSql: Record<TransactionQuery['sort'], string> = {
  booked_date_desc:
    'COALESCE(posted_date, booked_date) DESC, booked_date DESC, id DESC',
  booked_date_asc:
    'COALESCE(posted_date, booked_date) ASC, booked_date ASC, id ASC',
  amount_desc:
    'ABS(amount_base) DESC NULLS LAST, COALESCE(posted_date, booked_date) DESC, booked_date DESC, id DESC',
  amount_asc:
    'ABS(amount_base) ASC NULLS LAST, COALESCE(posted_date, booked_date) DESC, booked_date DESC, id DESC'
};

function addValue(values: unknown[], value: unknown): string {
  values.push(value);
  return `$${values.length}`;
}

function escapeLike(value: string) {
  return value.replace(/[\\%_]/g, '\\$&');
}

export function buildTransactionQueries(spec: TransactionQuery, transactionId?: string): {
  data: BuiltQuery;
  count: BuiltQuery;
} {
  const values: unknown[] = [];
  const conditions: string[] = [];

  if (spec.accountId) conditions.push(`account_id = ${addValue(values, spec.accountId)}`);
  if (transactionId) conditions.push(`id = ${addValue(values, transactionId)}::uuid`);
  if (spec.market) conditions.push(`market_code = ${addValue(values, spec.market)}`);
  if (spec.categoryId) conditions.push(`category_id = ${addValue(values, spec.categoryId)}`);
  if (spec.direction) conditions.push(`direction = ${addValue(values, spec.direction)}`);
  if (spec.from) conditions.push(`booked_date >= ${addValue(values, spec.from)}::date`);
  if (spec.to) conditions.push(`booked_date <= ${addValue(values, spec.to)}::date`);
  if (spec.search) {
    const parameter = addValue(values, `%${escapeLike(spec.search)}%`);
    conditions.push(
      `(description_raw ILIKE ${parameter} ESCAPE '\\' OR merchant_name ILIKE ${parameter} ESCAPE '\\')`
    );
  }

  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
  const common = `
    WITH setting AS (
      SELECT base_currency
      FROM ledger_settings
      WHERE singleton
    ), opening_native AS (
      SELECT DISTINCT ON (s.account_id)
        s.account_id,
        s.period_start,
        s.opening_balance,
        a.native_currency,
        setting.base_currency
      FROM statement s
      JOIN account a ON a.id = s.account_id
      CROSS JOIN setting
      WHERE s.opening_balance IS NOT NULL
        AND s.reconcile_status IN ('ok', 'gap', 'pending')
      ORDER BY s.account_id, s.period_start, s.id
    ), opening AS (
      SELECT
        opening_native.account_id,
        opening_native.opening_balance,
        CASE
          WHEN opening_native.opening_balance IS NULL THEN NULL
          WHEN opening_native.native_currency = opening_native.base_currency
            THEN opening_native.opening_balance
          WHEN historical_fx.rate IS NOT NULL
            THEN ROUND(opening_native.opening_balance * historical_fx.rate, 2)
          ELSE NULL
        END AS opening_balance_base
      FROM opening_native
      LEFT JOIN LATERAL (
        SELECT rate
        FROM fx_rate
        WHERE base = opening_native.native_currency
          AND quote = opening_native.base_currency
          AND as_of <= opening_native.period_start
          AND as_of >= opening_native.period_start - ${FX_MAX_STALENESS_DAYS}
        ORDER BY as_of DESC
        LIMIT 1
      ) historical_fx ON opening_native.native_currency <> opening_native.base_currency
    ), base AS (
      SELECT
        t.id,
        t.account_id,
        t.statement_id,
        source_statement.period_start AS statement_period_start,
        a.display_name AS account_name,
        a.market_code,
        t.booked_date,
        t.posted_date,
        t.description_raw,
        m.canonical_name AS merchant_name,
        t.category_id,
        c.name AS category_name,
        t.category_source,
        t.category_confidence,
        t.amount_native,
        t.currency_native,
        t.original_amount,
        t.original_currency,
        t.amount_base,
        t.currency_base,
        t.fx_rate,
        t.fx_rate_date,
        t.fx_fee_amount_native,
        t.is_fx_fee,
        t.direction,
        t.enrichment,
        COALESCE(t.posted_date, t.booked_date) AS effective_date
      FROM txn t
      JOIN account a ON a.id = t.account_id
      LEFT JOIN statement source_statement ON source_statement.id = t.statement_id
      LEFT JOIN merchant m ON m.id = t.merchant_id
      LEFT JOIN category c ON c.id = t.category_id
    ), ledger AS (
      SELECT
        base.*,
        COALESCE(o.opening_balance, 0) + SUM(base.amount_native) OVER (
          PARTITION BY base.account_id
          ORDER BY
            base.effective_date,
            base.statement_period_start NULLS LAST,
            base.posted_date NULLS LAST,
            base.booked_date,
            base.id
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS running_balance_native,
        CASE
          WHEN COUNT(*) FILTER (WHERE base.amount_base IS NULL) OVER (
            PARTITION BY base.account_id
            ORDER BY
              base.effective_date,
              base.statement_period_start NULLS LAST,
              base.posted_date NULLS LAST,
              base.booked_date,
              base.id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          ) > 0 THEN NULL
          WHEN o.opening_balance IS NULL THEN SUM(base.amount_base) OVER (
            PARTITION BY base.account_id
            ORDER BY
              base.effective_date,
              base.statement_period_start NULLS LAST,
              base.posted_date NULLS LAST,
              base.booked_date,
              base.id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )
          WHEN o.opening_balance_base IS NULL THEN NULL
          ELSE o.opening_balance_base + SUM(base.amount_base) OVER (
            PARTITION BY base.account_id
            ORDER BY
              base.effective_date,
              base.statement_period_start NULLS LAST,
              base.posted_date NULLS LAST,
              base.booked_date,
              base.id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )
        END AS running_balance_base
      FROM base
      LEFT JOIN opening o ON o.account_id = base.account_id
    )`;

  const limit = addValue(values, spec.pageSize);
  const offset = addValue(values, (spec.page - 1) * spec.pageSize);
  const dataText = `${common}
    SELECT
      id,
      account_id,
      account_name,
      booked_date::text,
      posted_date::text,
      description_raw,
      merchant_name,
      category_id,
      category_name,
      category_source,
      category_confidence::text,
      amount_native::text,
      currency_native,
      original_amount::text,
      original_currency,
      amount_base::text,
      currency_base,
      fx_rate::text,
      fx_rate_date::text,
      fx_fee_amount_native::text,
      is_fx_fee,
      direction,
      enrichment,
      running_balance_native::text AS running_balance,
      running_balance_native::text,
      running_balance_base::text
    FROM ledger
    ${where}
    ORDER BY ${transactionSortSql[spec.sort]}
    LIMIT ${limit} OFFSET ${offset}`;

  const countValues = values.slice(0, -2);
  const countText = `${common}
    SELECT COUNT(*)::int AS total
    FROM ledger
    ${where}`;

  return {
    data: { text: dataText, values },
    count: { text: countText, values: countValues }
  };
}

function buildAnalyticsConditions(spec: AnalyticsQuery, values: unknown[], alias = 't') {
  const conditions: string[] = [];
  if (spec.accountId) conditions.push(`${alias}.account_id = ${addValue(values, spec.accountId)}`);
  if (spec.market) {
    conditions.push(`EXISTS (
      SELECT 1 FROM account scoped_account
      WHERE scoped_account.id = ${alias}.account_id
        AND scoped_account.market_code = ${addValue(values, spec.market)}
    )`);
  }
  if (spec.from) conditions.push(`${alias}.booked_date >= ${addValue(values, spec.from)}::date`);
  if (spec.to) conditions.push(`${alias}.booked_date <= ${addValue(values, spec.to)}::date`);
  return conditions;
}

export function buildBalanceQuery(spec: AnalyticsQuery): BuiltQuery {
  const values: unknown[] = [];
  const openingContribution = spec.accountId
    ? 'opening_base'
    : `CASE
        WHEN kind = 'credit_card' THEN -opening_base
        ELSE opening_base
      END`;
  const transactionContribution = spec.accountId
    ? 't.amount_base'
    : `CASE
        WHEN selected.kind = 'credit_card' THEN -t.amount_base
        ELSE t.amount_base
      END`;
  const selectedAccountConditions = spec.accountId
    ? [`a.id = ${addValue(values, spec.accountId)}`]
    : [];
  if (spec.market) {
    selectedAccountConditions.push(`a.market_code = ${addValue(values, spec.market)}`);
  }
  // Once an unvalued transaction enters a consolidated running series, every
  // later reporting balance is unknown until FX enrichment fills that gap. Omit
  // those points instead of coercing SQL NULL to a misleading chart zero.
  const outerConditions: string[] = ['balance IS NOT NULL'];
  if (spec.from) outerConditions.push(`date >= ${addValue(values, spec.from)}::date`);
  if (spec.to) outerConditions.push(`date <= ${addValue(values, spec.to)}::date`);
  const selectedWhere = selectedAccountConditions.length
    ? `WHERE ${selectedAccountConditions.join(' AND ')}`
    : '';
  const outerWhere = outerConditions.length ? `WHERE ${outerConditions.join(' AND ')}` : '';

  return {
    text: `
      WITH setting AS (
        SELECT base_currency
        FROM ledger_settings
        WHERE singleton
      ), selected_accounts AS (
        SELECT
          a.id,
          a.kind,
          a.native_currency,
          setting.base_currency,
          EXISTS (
            SELECT 1
            FROM statement unreconciled
            WHERE unreconciled.account_id = a.id
              AND unreconciled.reconcile_status = 'mismatch'
              AND (
                unreconciled.opening_balance IS NOT NULL
                OR unreconciled.closing_balance IS NOT NULL
              )
          ) AS has_unreconciled_balance
        FROM account a
        CROSS JOIN setting
        ${selectedWhere}
      ), first_statements AS (
        SELECT
          selected.id AS account_id,
          selected.kind,
          selected.native_currency,
          selected.base_currency,
          selected.has_unreconciled_balance,
          first_statement.period_start,
          first_statement.opening_balance
        FROM selected_accounts selected
        LEFT JOIN LATERAL (
          SELECT s.period_start, s.opening_balance
          FROM statement s
          WHERE s.account_id = selected.id
            AND s.opening_balance IS NOT NULL
            AND s.reconcile_status IN ('ok', 'gap', 'pending')
          ORDER BY s.period_start, s.id
          LIMIT 1
        ) first_statement ON true
      ), opening_accounts AS (
        SELECT
          first_statements.*,
          CASE
            WHEN first_statements.opening_balance IS NULL THEN NULL
            WHEN first_statements.native_currency = first_statements.base_currency
              THEN first_statements.opening_balance
            WHEN historical_fx.rate IS NOT NULL
              THEN ROUND(first_statements.opening_balance * historical_fx.rate, 2)
            ELSE NULL
          END AS opening_base
        FROM first_statements
        LEFT JOIN LATERAL (
          SELECT rate
          FROM fx_rate
          WHERE base = first_statements.native_currency
            AND quote = first_statements.base_currency
            AND as_of <= first_statements.period_start
            AND as_of >= first_statements.period_start - ${FX_MAX_STALENESS_DAYS}
          ORDER BY as_of DESC
          LIMIT 1
        ) historical_fx ON first_statements.native_currency <> first_statements.base_currency
      ), opening AS (
        SELECT
          COALESCE(
            SUM(${openingContribution}),
            0
          ) AS amount,
          CASE
            WHEN BOOL_AND(
              opening_balance IS NOT NULL
              AND opening_base IS NOT NULL
              AND NOT has_unreconciled_balance
            )
              THEN 'balance'
            ELSE 'net_activity'
          END AS basis
        FROM opening_accounts
      ), daily AS (
        SELECT
          COALESCE(t.posted_date, t.booked_date) AS date,
          SUM(${transactionContribution}) AS delta,
          COUNT(*) FILTER (WHERE t.amount_base IS NULL) AS pending_fx_count
        FROM txn t
        JOIN selected_accounts selected ON selected.id = t.account_id
        GROUP BY COALESCE(t.posted_date, t.booked_date)
      ), running AS (
        SELECT
          date,
          CASE
            WHEN SUM(pending_fx_count) OVER (
              ORDER BY date ROWS UNBOUNDED PRECEDING
            ) > 0 THEN NULL
            ELSE (SELECT amount FROM opening)
              + SUM(delta) OVER (ORDER BY date ROWS UNBOUNDED PRECEDING)
          END AS balance,
          (SELECT basis FROM opening) AS basis
        FROM daily
      )
      SELECT date::text, balance::text, basis
      FROM running
      ${outerWhere}
      ORDER BY date`,
    values
  };
}

export function buildCashflowQuery(spec: AnalyticsQuery): BuiltQuery {
  const values: unknown[] = [];
  const conditions = buildAnalyticsConditions(spec, values);
  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
  const flow = `COALESCE(
    NULLIF(t.enrichment #>> '{categorization,flow_type}', ''),
    (${transactionFlowSql('t', 'a')})
  )`;
  return {
    text: `
      WITH classified AS (
        SELECT
          date_trunc('month', t.booked_date)::date AS period,
          CASE
            WHEN ${flow} = 'transfer' THEN 0
            WHEN a.kind = 'credit_card'
              AND t.amount_base < 0
              AND t.direction IN ('credit', 'refund')
              THEN ABS(t.amount_base)
            WHEN a.kind IN ('chequing', 'savings', 'wallet')
              AND t.amount_base > 0
              THEN t.amount_base
            ELSE 0
          END AS inflow,
          CASE
            WHEN ${flow} = 'transfer' THEN 0
            WHEN a.kind = 'credit_card'
              AND t.amount_base > 0
              AND t.direction <> 'payment'
              THEN t.amount_base
            WHEN a.kind IN ('chequing', 'savings', 'wallet')
              AND t.amount_base < 0
              THEN ABS(t.amount_base)
            ELSE 0
          END AS outflow,
          CASE
            WHEN a.kind = 'credit_card' AND t.direction = 'payment'
              THEN ABS(t.amount_base)
            ELSE 0
          END AS card_payments
        FROM txn t
        JOIN account a ON a.id = t.account_id
        ${where}
      )
      SELECT
        period::text,
        COALESCE(SUM(inflow), 0)::text AS inflow,
        COALESCE(SUM(outflow), 0)::text AS outflow,
        COALESCE(SUM(card_payments), 0)::text AS card_payments,
        (COALESCE(SUM(inflow), 0) - COALESCE(SUM(outflow), 0))::text AS net
      FROM classified
      GROUP BY period
      ORDER BY period`,
    values
  };
}

export function transactionFlowSql(transactionAlias = 't', accountAlias = 'a') {
  return `COALESCE(
    NULLIF(${transactionAlias}.enrichment #>> '{categorization,flow_type}', ''),
    CASE
      WHEN ${transactionAlias}.direction IN ('fee', 'interest') THEN 'fee'
      WHEN ${transactionAlias}.direction = 'payment' THEN 'transfer'
      WHEN ${transactionAlias}.direction = 'refund' THEN 'refund'
      WHEN ${accountAlias}.kind = 'credit_card'
        AND ${transactionAlias}.amount_native < 0 THEN 'refund'
      WHEN ${accountAlias}.kind = 'credit_card' THEN 'spend'
      WHEN ${transactionAlias}.amount_native > 0 THEN 'income'
      ELSE 'spend'
    END
  )`;
}

export function buildNetWorthQuery(spec: Pick<AnalyticsQuery, 'accountId' | 'market'> = {}): BuiltQuery {
  const values: unknown[] = [];
  const conditions: string[] = [];
  if (spec.accountId) conditions.push(`a.id = ${addValue(values, spec.accountId)}::uuid`);
  if (spec.market) conditions.push(`a.market_code = ${addValue(values, spec.market)}`);
  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
  return {
    text: `
      WITH setting AS (
        SELECT base_currency
        FROM ledger_settings
        WHERE singleton
      ), positions AS (
        SELECT
          a.id AS account_id,
          a.display_name,
          a.kind,
          a.native_currency,
          setting.base_currency,
          CASE
            WHEN latest.closing_balance IS NOT NULL
              AND latest.reconcile_status IN ('ok', 'gap', 'pending')
              THEN latest.closing_balance + COALESCE(activity.after_latest, 0)
            ELSE COALESCE(earliest.opening_balance, 0) + COALESCE(activity.total, 0)
          END AS native_balance,
          (
            latest.closing_balance IS NOT NULL
            AND latest.reconcile_status IN ('ok', 'gap', 'pending')
          ) OR (
            latest.closing_balance IS NULL
            AND earliest.opening_balance IS NOT NULL
          ) AS verified
        FROM account a
        CROSS JOIN setting
        LEFT JOIN LATERAL (
          SELECT s.period_end, s.closing_balance, s.reconcile_status
          FROM statement s
          WHERE s.account_id = a.id
            AND s.closing_balance IS NOT NULL
          ORDER BY s.period_end DESC, s.id DESC
          LIMIT 1
        ) latest ON true
        LEFT JOIN LATERAL (
          SELECT s.opening_balance
          FROM statement s
          WHERE s.account_id = a.id
            AND s.opening_balance IS NOT NULL
            AND s.reconcile_status IN ('ok', 'gap', 'pending')
          ORDER BY s.period_start, s.id
          LIMIT 1
        ) earliest ON true
        LEFT JOIN LATERAL (
          SELECT
            COALESCE(SUM(t.amount_native), 0) AS total,
            COALESCE(
              SUM(t.amount_native) FILTER (
                WHERE COALESCE(t.posted_date, t.booked_date) > latest.period_end
              ),
              0
            ) AS after_latest
          FROM txn t
          WHERE t.account_id = a.id
        ) activity ON true
        ${where}
      ), valued AS (
        SELECT
          positions.*,
          CASE
            WHEN positions.native_currency = positions.base_currency THEN 1
            ELSE current_fx.rate
          END AS fx_rate,
          CASE
            WHEN positions.native_currency = positions.base_currency THEN CURRENT_DATE
            ELSE current_fx.as_of
          END AS fx_rate_date
        FROM positions
        LEFT JOIN LATERAL (
          SELECT rate, as_of
          FROM fx_rate
          WHERE base = positions.native_currency
            AND quote = positions.base_currency
            AND as_of <= CURRENT_DATE
            AND as_of >= CURRENT_DATE - ${FX_MAX_STALENESS_DAYS}
          ORDER BY as_of DESC
          LIMIT 1
        ) current_fx ON positions.native_currency <> positions.base_currency
      ), contributions AS (
        SELECT
          valued.*,
          CASE
            WHEN NOT verified OR fx_rate IS NULL THEN NULL
            WHEN kind = 'credit_card' THEN -ROUND(native_balance * fx_rate, 2)
            ELSE ROUND(native_balance * fx_rate, 2)
          END AS contribution,
          CASE
            WHEN NOT verified THEN 'unverified_balance'
            WHEN fx_rate IS NULL THEN 'missing_fx_rate'
            ELSE NULL
          END AS excluded_reason
        FROM valued
      )
      SELECT
        account_id,
        display_name,
        kind,
        native_currency,
        native_balance::text,
        CASE
          WHEN contribution IS NULL THEN NULL
          ELSE ROUND(native_balance * fx_rate, 2)::text
        END AS base_value,
        contribution::text,
        fx_rate::text,
        fx_rate_date::text,
        excluded_reason,
        COALESCE(SUM(GREATEST(contribution, 0)) OVER (), 0)::text AS assets,
        COALESCE(SUM(ABS(LEAST(contribution, 0))) OVER (), 0)::text AS liabilities,
        COALESCE(SUM(contribution) OVER (), 0)::text AS net_worth,
        base_currency,
        BOOL_OR(excluded_reason IS NOT NULL) OVER () AS is_partial,
        CURRENT_DATE::text AS valuation_date
      FROM contributions
      ORDER BY display_name`,
    values
  };
}

export function buildFxAnalyticsQuery(spec: AnalyticsQuery, transactionId?: string): BuiltQuery {
  const values: unknown[] = [];
  const conditions = buildAnalyticsConditions(spec, values);
  if (transactionId) conditions.push(`t.id = ${addValue(values, transactionId)}::uuid`);
  conditions.push(`(
    (t.original_amount IS NOT NULL AND t.original_currency IS NOT NULL)
    OR t.fx_fee_amount_native IS NOT NULL
    OR t.is_fx_fee
    OR t.amount_base IS NULL
  )`);
  const where = `WHERE ${conditions.join(' AND ')}`;
  return {
    text: `
      WITH setting AS (
        SELECT base_currency
        FROM ledger_settings
        WHERE singleton
      ), evidence AS (
        SELECT
          t.id AS transaction_id,
          t.account_id,
          a.display_name AS account_name,
          t.booked_date,
          t.description_raw,
          ABS(t.original_amount) AS foreign_amount,
          t.original_currency AS foreign_currency,
          ABS(t.amount_native) AS charged_amount_native,
          GREATEST(
            ABS(t.amount_native) - COALESCE(t.fx_fee_amount_native, 0),
            0
          ) AS conversion_amount_native,
          CASE
            WHEN t.is_fx_fee THEN ABS(t.amount_native)
            ELSE COALESCE(t.fx_fee_amount_native, 0)
          END AS explicit_fee_native,
          t.is_fx_fee,
          a.native_currency,
          t.fx_rate AS native_to_base_rate,
          setting.base_currency
        FROM txn t
        JOIN account a ON a.id = t.account_id
        CROSS JOIN setting
        ${where}
      ), compared AS (
        SELECT
          evidence.*,
          CASE
            WHEN evidence.foreign_amount IS NULL OR evidence.foreign_amount = 0 THEN NULL
            ELSE evidence.conversion_amount_native / evidence.foreign_amount
          END AS bank_applied_rate,
          market.rate AS market_rate,
          market.as_of AS market_rate_date,
          market.source AS market_rate_source
        FROM evidence
        LEFT JOIN LATERAL (
          SELECT rate, as_of, source
          FROM fx_rate
          WHERE base = evidence.foreign_currency
            AND quote = evidence.native_currency
            AND as_of <= evidence.booked_date
            AND as_of >= evidence.booked_date - ${FX_MAX_STALENESS_DAYS}
          ORDER BY as_of DESC
          LIMIT 1
        ) market ON evidence.foreign_currency IS NOT NULL
                AND evidence.foreign_currency <> evidence.native_currency
      ), fees AS (
        SELECT
          compared.*,
          CASE
            WHEN foreign_currency IS NULL THEN NULL
            WHEN foreign_currency = native_currency THEN 1
            ELSE market_rate
          END AS resolved_market_rate
        FROM compared
      ), calculated AS (
        SELECT
          fees.*,
          CASE
            WHEN resolved_market_rate IS NULL OR bank_applied_rate IS NULL THEN NULL
            ELSE ROUND((bank_applied_rate / resolved_market_rate - 1) * 100, 4)
          END AS markup_percent,
          CASE
            WHEN resolved_market_rate IS NULL OR bank_applied_rate IS NULL THEN NULL
            ELSE ROUND((bank_applied_rate - resolved_market_rate) * foreign_amount, 2)
          END AS estimated_markup_native,
          CASE
            WHEN native_to_base_rate IS NULL THEN NULL
            ELSE ROUND(explicit_fee_native * native_to_base_rate, 2)
          END AS explicit_fee_base
        FROM fees
      ), valued AS (
        SELECT
          calculated.*,
          CASE
            WHEN estimated_markup_native IS NULL OR native_to_base_rate IS NULL THEN NULL
            ELSE ROUND(estimated_markup_native * native_to_base_rate, 2)
          END AS estimated_markup_base,
          (
            native_to_base_rate IS NULL
            OR (
              foreign_amount IS NOT NULL
              AND (resolved_market_rate IS NULL OR native_to_base_rate IS NULL)
            )
          ) AS missing_rate
        FROM calculated
      )
      SELECT
        transaction_id,
        account_id,
        account_name,
        booked_date::text,
        description_raw,
        foreign_amount::text,
        foreign_currency,
        charged_amount_native::text,
        native_currency,
        bank_applied_rate::text,
        resolved_market_rate::text AS market_rate,
        CASE
          WHEN foreign_currency IS NULL THEN NULL
          WHEN foreign_currency = native_currency THEN booked_date::text
          ELSE market_rate_date::text
        END AS market_rate_date,
        CASE
          WHEN foreign_currency IS NULL THEN NULL
          WHEN foreign_currency = native_currency THEN 'identity'
          ELSE market_rate_source
        END AS market_rate_source,
        markup_percent::text,
        explicit_fee_native::text,
        explicit_fee_base::text,
        estimated_markup_native::text,
        estimated_markup_base::text,
        is_fx_fee,
        base_currency,
        COALESCE(
          SUM(explicit_fee_base) FILTER (WHERE explicit_fee_base IS NOT NULL) OVER (),
          0
        )::text AS total_explicit_fee_base,
        COALESCE(
          SUM(estimated_markup_base)
            FILTER (WHERE estimated_markup_base IS NOT NULL) OVER (),
          0
        )::text AS total_estimated_markup_base,
        COALESCE(
          SUM(COALESCE(explicit_fee_base, 0) + COALESCE(estimated_markup_base, 0)) OVER (),
          0
        )::text AS total_fx_cost_base,
        (COUNT(*) FILTER (WHERE missing_rate) OVER ())::int AS missing_rate_count
      FROM valued
      ORDER BY booked_date DESC, transaction_id DESC`,
    values
  };
}

export async function closePoolForTests() {
  if (pool) await pool.end();
  pool = undefined;
}
