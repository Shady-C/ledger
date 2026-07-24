import pg from 'pg';
import type { QueryResultRow } from 'pg';
import type { AnalyticsQuery, TransactionQuery } from '@ledger/shared-types';

import { databaseConfig } from './env.js';

const { Pool } = pg;
let pool: pg.Pool | undefined;

export function getPool(): pg.Pool {
  if (!pool) pool = new Pool(databaseConfig());
  return pool;
}

export function query<T extends QueryResultRow>(text: string, values: readonly unknown[] = []) {
  return getPool().query<T>(text, [...values]);
}

type BuiltQuery = { text: string; values: unknown[] };

export const accountsSummarySql = `
  SELECT
    a.id,
    a.display_name,
    i.name AS institution_name,
    a.kind,
    a.native_currency,
    a.account_ref_masked,
    (
      CASE
        WHEN latest.closing_balance IS NOT NULL THEN
          latest.closing_balance
          + COALESCE(SUM(t.amount_native) FILTER (WHERE t.booked_date > latest.period_end), 0)
        ELSE
          COALESCE(earliest.opening_balance, 0) + COALESCE(SUM(t.amount_native), 0)
      END
    )::text AS current_balance,
    latest.period_end::text AS last_statement_date
  FROM account a
  LEFT JOIN institution i ON i.id = a.institution_id
  LEFT JOIN LATERAL (
    SELECT s.period_end, s.closing_balance
    FROM statement s
    WHERE s.account_id = a.id
    ORDER BY s.period_end DESC, s.id DESC
    LIMIT 1
  ) latest ON true
  LEFT JOIN LATERAL (
    SELECT s.opening_balance
    FROM statement s
    WHERE s.account_id = a.id
    ORDER BY s.period_start, s.id
    LIMIT 1
  ) earliest ON true
  LEFT JOIN txn t ON t.account_id = a.id
  GROUP BY
    a.id,
    a.display_name,
    i.name,
    a.kind,
    a.native_currency,
    a.account_ref_masked,
    latest.closing_balance,
    latest.period_end,
    earliest.opening_balance
  ORDER BY a.display_name
`;

const transactionSortSql: Record<TransactionQuery['sort'], string> = {
  booked_date_desc: 'booked_date DESC, id DESC',
  booked_date_asc: 'booked_date ASC, id ASC',
  amount_desc: 'amount_base DESC, booked_date DESC, id DESC',
  amount_asc: 'amount_base ASC, booked_date DESC, id DESC'
};

function addValue(values: unknown[], value: unknown): string {
  values.push(value);
  return `$${values.length}`;
}

function escapeLike(value: string) {
  return value.replace(/[\\%_]/g, '\\$&');
}

export function buildTransactionQueries(spec: TransactionQuery): {
  data: BuiltQuery;
  count: BuiltQuery;
} {
  const values: unknown[] = [];
  const conditions: string[] = [];

  if (spec.accountId) conditions.push(`account_id = ${addValue(values, spec.accountId)}`);
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
    WITH opening AS (
      SELECT DISTINCT ON (s.account_id)
        s.account_id,
        COALESCE(s.opening_balance, 0) AS opening_balance
      FROM statement s
      ORDER BY s.account_id, s.period_start, s.id
    ), ledger AS (
      SELECT
        t.id,
        t.account_id,
        a.display_name AS account_name,
        t.booked_date,
        t.posted_date,
        t.description_raw,
        m.canonical_name AS merchant_name,
        t.category_id,
        c.name AS category_name,
        t.amount_native,
        t.currency_native,
        t.amount_base,
        t.currency_base,
        t.fx_rate,
        t.direction,
        t.enrichment,
        COALESCE(o.opening_balance, 0) + SUM(t.amount_base) OVER (
          PARTITION BY t.account_id
          ORDER BY t.booked_date, t.id
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS running_balance
      FROM txn t
      JOIN account a ON a.id = t.account_id
      LEFT JOIN opening o ON o.account_id = t.account_id
      LEFT JOIN merchant m ON m.id = t.merchant_id
      LEFT JOIN category c ON c.id = t.category_id
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
      amount_native::text,
      currency_native,
      amount_base::text,
      currency_base,
      fx_rate::text,
      direction,
      enrichment,
      running_balance::text
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
  if (spec.from) conditions.push(`${alias}.booked_date >= ${addValue(values, spec.from)}::date`);
  if (spec.to) conditions.push(`${alias}.booked_date <= ${addValue(values, spec.to)}::date`);
  return conditions;
}

export function buildBalanceQuery(spec: AnalyticsQuery): BuiltQuery {
  const values: unknown[] = [];
  const selectedAccountConditions = spec.accountId
    ? [`a.id = ${addValue(values, spec.accountId)}`]
    : [];
  const outerConditions: string[] = [];
  if (spec.from) outerConditions.push(`date >= ${addValue(values, spec.from)}::date`);
  if (spec.to) outerConditions.push(`date <= ${addValue(values, spec.to)}::date`);
  const selectedWhere = selectedAccountConditions.length
    ? `WHERE ${selectedAccountConditions.join(' AND ')}`
    : '';
  const outerWhere = outerConditions.length ? `WHERE ${outerConditions.join(' AND ')}` : '';

  return {
    text: `
      WITH selected_accounts AS (
        SELECT a.id
        FROM account a
        ${selectedWhere}
      ), opening AS (
        SELECT COALESCE(SUM(first_statement.opening_balance), 0) AS amount
        FROM selected_accounts selected
        LEFT JOIN LATERAL (
          SELECT COALESCE(s.opening_balance, 0) AS opening_balance
          FROM statement s
          WHERE s.account_id = selected.id
          ORDER BY s.period_start, s.id
          LIMIT 1
        ) first_statement ON true
      ), daily AS (
        SELECT t.booked_date AS date, SUM(t.amount_base) AS delta
        FROM txn t
        JOIN selected_accounts selected ON selected.id = t.account_id
        GROUP BY t.booked_date
      ), running AS (
        SELECT
          date,
          (SELECT amount FROM opening)
            + SUM(delta) OVER (ORDER BY date ROWS UNBOUNDED PRECEDING) AS balance
        FROM daily
      )
      SELECT date::text, balance::text
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
  return {
    text: `
      WITH classified AS (
        SELECT
          date_trunc('month', t.booked_date)::date AS period,
          CASE
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
            WHEN a.kind = 'credit_card'
              AND t.amount_base > 0
              AND t.direction <> 'payment'
              THEN t.amount_base
            WHEN a.kind IN ('chequing', 'savings', 'wallet')
              AND t.amount_base < 0
              THEN ABS(t.amount_base)
            ELSE 0
          END AS outflow
        FROM txn t
        JOIN account a ON a.id = t.account_id
        ${where}
      )
      SELECT
        period::text,
        COALESCE(SUM(inflow), 0)::text AS inflow,
        COALESCE(SUM(outflow), 0)::text AS outflow,
        (COALESCE(SUM(inflow), 0) - COALESCE(SUM(outflow), 0))::text AS net
      FROM classified
      GROUP BY period
      ORDER BY period`,
    values
  };
}

export async function closePoolForTests() {
  if (pool) await pool.end();
  pool = undefined;
}
