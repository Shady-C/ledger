import type {
  AccountSummary,
  CategorySummary,
  Institution,
  Transaction,
  TransactionPage
} from '@ledger/shared-types';

// `hasActivity` is an optional presentation hint; the API remains authoritative
// when enforcing kind and currency immutability.
export type AccountView = AccountSummary & { hasActivity?: boolean };
export type InstitutionView = Institution;
export type CategoryView = CategorySummary;
export type TransactionView = Transaction;
export type TransactionPageView = TransactionPage;
