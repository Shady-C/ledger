"""Deterministic Phase 2 analytics over canonical transaction-like inputs.

The functions in this module are deliberately persistence-free.  They accept
exact ``Decimal`` values and return immutable result records that a repository
can materialize in one analytics generation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from hashlib import sha256
from itertools import pairwise
from time import monotonic
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

MONEY_QUANTUM = Decimal("0.01")
RATIO_QUANTUM = Decimal("0.0001")
ONE_HUNDRED = Decimal("100")


class AnalyticsFlow(StrEnum):
    """Cash-flow meaning used by deterministic analytics."""

    SPEND = "spend"
    INCOME = "income"
    TRANSFER = "transfer"
    REFUND = "refund"
    FEE = "fee"


class CoverageStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class AggregateDimension(StrEnum):
    LEDGER = "ledger"
    ACCOUNT = "account"
    CATEGORY = "category"
    MERCHANT = "merchant"


class ComparisonBasis(StrEnum):
    ORIGINAL = "original"
    NATIVE = "native"
    BASE = "base"


class RecurringCadence(StrEnum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class Sensitivity(StrEnum):
    LOW = "low"
    BALANCED = "balanced"
    HIGH = "high"


class AnomalyMethod(StrEnum):
    MAD = "mad"
    IQR = "iqr"


class FindingType(StrEnum):
    UNUSUAL_AMOUNT = "unusual_amount"
    UNUSUAL_FREQUENCY = "unusual_frequency"
    MONTHLY_SPIKE = "monthly_spike"
    NEAR_DUPLICATE = "near_duplicate"
    RECURRING_PRICE_INCREASE = "recurring_price_increase"
    RECURRING_OVERDUE = "recurring_overdue"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    COVERAGE_GAP = "coverage_gap"
    PENDING_FX = "pending_fx"


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class AnalyticsTransaction:
    """Minimum canonical transaction projection required by Phase 2 analytics."""

    transaction_id: str
    account_id: str
    booked_date: date
    flow_type: AnalyticsFlow
    amount_native: Decimal
    currency_native: str
    amount_base: Decimal | None
    merchant_key: str | None = None
    merchant_id: str | None = None
    category_id: str | None = None
    original_amount: Decimal | None = None
    original_currency: str | None = None
    fx_fee_amount_native: Decimal | None = None
    direction: str | None = None
    is_reversal: bool = False

    def __post_init__(self) -> None:
        if not self.transaction_id.strip():
            raise ValueError("transaction_id must not be blank")
        if not self.account_id.strip():
            raise ValueError("account_id must not be blank")
        _require_money(self.amount_native, "amount_native")
        if self.amount_base is not None:
            _require_money(self.amount_base, "amount_base")
        if (self.original_amount is None) != (self.original_currency is None):
            raise ValueError("original_amount and original_currency must be present together")
        if self.original_amount is not None:
            _require_money(self.original_amount, "original_amount")
            assert self.original_currency is not None
            object.__setattr__(self, "original_currency", _currency(self.original_currency))
        if self.fx_fee_amount_native is not None:
            _require_money(self.fx_fee_amount_native, "fx_fee_amount_native")
        object.__setattr__(self, "currency_native", _currency(self.currency_native))
        if self.merchant_key is not None:
            normalized_merchant = self.merchant_key.strip().casefold()
            object.__setattr__(self, "merchant_key", normalized_merchant or None)
        if self.direction is not None:
            normalized_direction = self.direction.strip().casefold()
            object.__setattr__(self, "direction", normalized_direction or None)


@dataclass(frozen=True, slots=True)
class MonthlyTrend:
    period_start: date
    inflow_base: Decimal
    outflow_base: Decimal
    spending_base: Decimal
    net_base: Decimal
    transaction_count: int
    valued_count: int
    pending_fx_count: int
    pending_fx_by_currency: tuple[tuple[str, int], ...]
    coverage_status: CoverageStatus
    spending_change_from_previous: Decimal | None
    spending_change_percent: Decimal | None
    spending_change_from_previous_year: Decimal | None
    spending_change_from_previous_year_percent: Decimal | None
    trailing_three_month_average: Decimal
    trailing_three_month_median: Decimal


@dataclass(frozen=True, slots=True)
class MonthlyAggregate:
    period_start: date
    dimension_type: AggregateDimension
    dimension_key: str | None
    inflow_base: Decimal
    outflow_base: Decimal
    spending_base: Decimal
    net_base: Decimal
    transaction_count: int
    valued_count: int
    pending_fx_count: int
    pending_fx_by_currency: tuple[tuple[str, int], ...]
    coverage_status: CoverageStatus


@dataclass(frozen=True, slots=True)
class RecurringOccurrenceCandidate:
    transaction_id: str
    occurrence_date: date
    comparison_amount: Decimal
    base_amount: Decimal | None


@dataclass(frozen=True, slots=True)
class RecurringSeriesCandidate:
    detector_fingerprint: str
    merchant_key: str
    merchant_id: str | None
    flow_type: AnalyticsFlow
    cadence: RecurringCadence
    comparison_basis: ComparisonBasis
    comparison_currency: str
    occurrences: tuple[RecurringOccurrenceCandidate, ...]
    expected_amount: Decimal
    expected_next_date: date
    overdue: bool
    interval_stability: Decimal
    amount_stability: Decimal
    confidence: Decimal


@dataclass(frozen=True, slots=True)
class PriceIncrease:
    series_fingerprint: str
    latest_transaction_id: str
    comparison_currency: str
    previous_median: Decimal
    latest_amount: Decimal
    increase_amount: Decimal
    increase_percent: Decimal
    increase_base: Decimal | None


@dataclass(frozen=True, slots=True)
class AmountAnomaly:
    transaction_id: str
    merchant_key: str
    flow_type: AnalyticsFlow
    amount_base: Decimal
    baseline_median: Decimal
    deviation_base: Decimal
    method: AnomalyMethod
    score: Decimal | None
    prior_observation_count: int


@dataclass(frozen=True, slots=True)
class FrequencyAnomaly:
    merchant_key: str
    flow_type: AnalyticsFlow
    period_start: date
    transaction_count: int
    baseline_median: Decimal
    count_difference: Decimal
    method: AnomalyMethod
    score: Decimal | None
    prior_month_count: int


@dataclass(frozen=True, slots=True)
class MonthlySpike:
    dimension_type: AggregateDimension
    dimension_key: str
    period_start: date
    spending_base: Decimal
    baseline_median: Decimal
    difference_base: Decimal
    method: AnomalyMethod
    score: Decimal | None
    prior_month_count: int


@dataclass(frozen=True, slots=True)
class NearDuplicate:
    detector_fingerprint: str
    first_transaction_id: str
    second_transaction_id: str
    account_id: str
    merchant_key: str
    currency_native: str
    amount_native: Decimal
    days_apart: int


@dataclass(frozen=True, slots=True)
class InsightFindingCandidate:
    detector_fingerprint: str
    finding_type: FindingType
    severity: FindingSeverity
    headline: str
    evidence: Mapping[str, object]
    account_id: str | None = None
    transaction_id: str | None = None
    recurring_series_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsRunContext:
    run_id: str
    generation: int
    mode: str
    sensitivity: Sensitivity
    source_watermark: datetime | None


@dataclass(frozen=True, slots=True)
class RecurringReviewState:
    detector_fingerprint: str
    status: str
    cadence_override: RecurringCadence | None = None
    expected_amount_override: Decimal | None = None
    next_date_override: date | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsSnapshot:
    context: AnalyticsRunContext
    transactions: tuple[AnalyticsTransaction, ...]
    aggregate_transactions: tuple[AnalyticsTransaction, ...] | None = None
    affected_periods: tuple[date, ...] = ()
    previous_generation: int | None = None
    source_findings: tuple[InsightFindingCandidate, ...] = ()
    recurring_review_states: tuple[RecurringReviewState, ...] = ()


class AnalyticsRefreshRepository(Protocol):
    """Persistence seam used by the job handler and its in-memory tests."""

    def prepare_run(self, *, mode: str, run_id: str | None) -> AnalyticsSnapshot: ...

    def publish_run(
        self,
        *,
        snapshot: AnalyticsSnapshot,
        aggregates: Sequence[MonthlyAggregate],
        recurring_series: Sequence[RecurringSeriesCandidate],
        findings: Sequence[InsightFindingCandidate],
        result: Mapping[str, object],
    ) -> None: ...

    def fail_run(self, *, run_id: str, error: str) -> None: ...


@dataclass(slots=True)
class _MonthAccumulator:
    inflow: Decimal = Decimal("0")
    outflow: Decimal = Decimal("0")
    spending: Decimal = Decimal("0")
    transaction_count: int = 0
    valued_count: int = 0
    pending_by_currency: dict[str, int] = field(default_factory=dict)

    def add(self, transaction: AnalyticsTransaction) -> None:
        self.transaction_count += 1
        if transaction.amount_base is None:
            currency = transaction.currency_native
            self.pending_by_currency[currency] = self.pending_by_currency.get(currency, 0) + 1
            return

        self.valued_count += 1
        amount = abs(transaction.amount_base)
        if transaction.flow_type is AnalyticsFlow.INCOME:
            self.inflow += amount
        elif transaction.flow_type in {AnalyticsFlow.SPEND, AnalyticsFlow.FEE}:
            self.outflow += amount
            self.spending += amount
        elif transaction.flow_type is AnalyticsFlow.REFUND:
            self.outflow -= amount
            self.spending -= amount

    def result(
        self,
    ) -> tuple[
        Decimal,
        Decimal,
        Decimal,
        Decimal,
        int,
        int,
        int,
        tuple[tuple[str, int], ...],
        CoverageStatus,
    ]:
        pending_count = sum(self.pending_by_currency.values())
        coverage = CoverageStatus.PARTIAL if pending_count else CoverageStatus.COMPLETE
        return (
            self.inflow,
            self.outflow,
            self.spending,
            self.inflow - self.outflow,
            self.transaction_count,
            self.valued_count,
            pending_count,
            tuple(sorted(self.pending_by_currency.items())),
            coverage,
        )


@dataclass(frozen=True, slots=True)
class _SensitivityProfile:
    modified_z_threshold: Decimal
    minimum_difference_base: Decimal
    iqr_multiplier: Decimal


_SENSITIVITY: dict[Sensitivity, _SensitivityProfile] = {
    Sensitivity.LOW: _SensitivityProfile(Decimal("5.0"), Decimal("25.00"), Decimal("3")),
    Sensitivity.BALANCED: _SensitivityProfile(
        Decimal("3.5"), Decimal("10.00"), Decimal("1.5")
    ),
    Sensitivity.HIGH: _SensitivityProfile(Decimal("2.5"), Decimal("5.00"), Decimal("1")),
}


_CADENCE_RANGES: dict[RecurringCadence, tuple[int, int]] = {
    RecurringCadence.WEEKLY: (5, 9),
    RecurringCadence.BIWEEKLY: (12, 16),
    RecurringCadence.MONTHLY: (25, 35),
    RecurringCadence.QUARTERLY: (80, 100),
    RecurringCadence.ANNUAL: (330, 400),
}

_CADENCE_TYPICAL_DAYS: dict[RecurringCadence, int] = {
    RecurringCadence.WEEKLY: 7,
    RecurringCadence.BIWEEKLY: 14,
    RecurringCadence.MONTHLY: 30,
    RecurringCadence.QUARTERLY: 90,
    RecurringCadence.ANNUAL: 365,
}


def calculate_monthly_trends(
    transactions: Iterable[AnalyticsTransaction],
) -> tuple[MonthlyTrend, ...]:
    """Return gap-filled CAD ledger trends with explicit FX coverage metadata."""

    rows = tuple(transactions)
    if not rows:
        return ()

    accumulators: dict[date, _MonthAccumulator] = defaultdict(_MonthAccumulator)
    for transaction in rows:
        accumulators[_month_start(transaction.booked_date)].add(transaction)

    first_month = min(accumulators)
    last_month = max(accumulators)
    base_rows: list[
        tuple[
            date,
            Decimal,
            Decimal,
            Decimal,
            Decimal,
            int,
            int,
            int,
            tuple[tuple[str, int], ...],
            CoverageStatus,
        ]
    ] = []
    for period_start in _month_range(first_month, last_month):
        base_rows.append((period_start, *accumulators[period_start].result()))

    trends: list[MonthlyTrend] = []
    for index, row in enumerate(base_rows):
        (
            period_start,
            inflow,
            outflow,
            spending,
            net,
            transaction_count,
            valued_count,
            pending_count,
            pending_by_currency,
            coverage,
        ) = row
        previous = base_rows[index - 1][3] if index >= 1 else None
        previous_year = base_rows[index - 12][3] if index >= 12 else None
        trailing_spending = [item[3] for item in base_rows[max(0, index - 2) : index + 1]]
        trends.append(
            MonthlyTrend(
                period_start=period_start,
                inflow_base=inflow,
                outflow_base=outflow,
                spending_base=spending,
                net_base=net,
                transaction_count=transaction_count,
                valued_count=valued_count,
                pending_fx_count=pending_count,
                pending_fx_by_currency=pending_by_currency,
                coverage_status=coverage,
                spending_change_from_previous=(
                    spending - previous if previous is not None else None
                ),
                spending_change_percent=_percentage_change(previous, spending),
                spending_change_from_previous_year=(
                    spending - previous_year if previous_year is not None else None
                ),
                spending_change_from_previous_year_percent=_percentage_change(
                    previous_year, spending
                ),
                trailing_three_month_average=_money(
                    sum(trailing_spending, Decimal("0")) / Decimal(len(trailing_spending))
                ),
                trailing_three_month_median=_median(trailing_spending),
            )
        )
    return tuple(trends)


def calculate_monthly_aggregates(
    transactions: Iterable[AnalyticsTransaction],
) -> tuple[MonthlyAggregate, ...]:
    """Build materializable ledger/account/category/merchant monthly rows."""

    rows = tuple(transactions)
    if not rows:
        return ()
    accumulators: dict[tuple[date, AggregateDimension, str | None], _MonthAccumulator] = {}
    for transaction in rows:
        period_start = _month_start(transaction.booked_date)
        dimensions: list[tuple[AggregateDimension, str | None]] = [
            (AggregateDimension.LEDGER, None),
            (AggregateDimension.ACCOUNT, transaction.account_id),
        ]
        if transaction.category_id is not None:
            dimensions.append((AggregateDimension.CATEGORY, transaction.category_id))
        if transaction.merchant_id is not None:
            dimensions.append((AggregateDimension.MERCHANT, transaction.merchant_id))
        for dimension_type, dimension_key in dimensions:
            key = (period_start, dimension_type, dimension_key)
            accumulator = accumulators.setdefault(key, _MonthAccumulator())
            accumulator.add(transaction)

    first_month = min(_month_start(transaction.booked_date) for transaction in rows)
    last_month = max(_month_start(transaction.booked_date) for transaction in rows)
    for period_start in _month_range(first_month, last_month):
        accumulators.setdefault(
            (period_start, AggregateDimension.LEDGER, None),
            _MonthAccumulator(),
        )

    results: list[MonthlyAggregate] = []
    for (period_start, dimension_type, dimension_key), accumulator in sorted(
        accumulators.items(), key=lambda item: (item[0][0], item[0][1].value, item[0][2] or "")
    ):
        (
            inflow,
            outflow,
            spending,
            net,
            transaction_count,
            valued_count,
            pending_count,
            pending_by_currency,
            coverage,
        ) = accumulator.result()
        results.append(
            MonthlyAggregate(
                period_start=period_start,
                dimension_type=dimension_type,
                dimension_key=dimension_key,
                inflow_base=inflow,
                outflow_base=outflow,
                spending_base=spending,
                net_base=net,
                transaction_count=transaction_count,
                valued_count=valued_count,
                pending_fx_count=pending_count,
                pending_fx_by_currency=pending_by_currency,
                coverage_status=coverage,
            )
        )
    return tuple(results)


def detect_recurring_series(
    transactions: Iterable[AnalyticsTransaction],
    *,
    as_of: date | None = None,
) -> tuple[RecurringSeriesCandidate, ...]:
    """Detect stable weekly through annual merchant-and-flow series."""

    groups: dict[tuple[str, AnalyticsFlow], list[AnalyticsTransaction]] = defaultdict(list)
    for transaction in transactions:
        if (
            transaction.merchant_key is not None
            and transaction.flow_type in {AnalyticsFlow.SPEND, AnalyticsFlow.INCOME}
            and abs(transaction.amount_native) > 0
        ):
            groups[(transaction.merchant_key, transaction.flow_type)].append(transaction)

    candidates: list[RecurringSeriesCandidate] = []
    for (merchant_key, flow_type), group in sorted(
        groups.items(), key=lambda item: (item[0][0], item[0][1].value)
    ):
        ordered = sorted(
            group,
            key=lambda transaction: (transaction.booked_date, transaction.transaction_id),
        )
        if len(ordered) < 2:
            continue
        intervals = [
            (current.booked_date - previous.booked_date).days
            for previous, current in pairwise(ordered)
        ]
        cadence_and_stability = _cadence(intervals)
        if cadence_and_stability is None:
            continue
        cadence, interval_stability = cadence_and_stability
        if cadence is not RecurringCadence.ANNUAL and len(ordered) < 3:
            continue

        comparison = _comparison_values(ordered)
        if comparison is None:
            continue
        basis, currency, occurrences = comparison
        amounts = [occurrence.comparison_amount for occurrence in occurrences]
        expected_amount = _median(amounts)
        stable_count = sum(
            1
            for amount in amounts
            if abs(amount - expected_amount) <= expected_amount * Decimal("0.10")
        )
        amount_stability = _ratio(stable_count, len(amounts))
        median_interval = _median([Decimal(interval) for interval in intervals])
        expected_days = int(median_interval.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        expected_next_date = ordered[-1].booked_date + timedelta(days=expected_days)
        evaluation_date = as_of if as_of is not None else date.today()
        fingerprint = _fingerprint(
            "recurring",
            merchant_key,
            flow_type.value,
            basis.value,
            currency,
        )
        confidence = (
            interval_stability * Decimal("0.55")
            + amount_stability * Decimal("0.25")
            + Decimal("0.10")  # merchant identity is exact within the group
            + Decimal("0.10")  # flow direction is exact within the group
        ).quantize(RATIO_QUANTUM)
        candidates.append(
            RecurringSeriesCandidate(
                detector_fingerprint=fingerprint,
                merchant_key=merchant_key,
                merchant_id=_consistent_merchant_id(ordered),
                flow_type=flow_type,
                cadence=cadence,
                comparison_basis=basis,
                comparison_currency=currency,
                occurrences=occurrences,
                expected_amount=expected_amount,
                expected_next_date=expected_next_date,
                overdue=evaluation_date > expected_next_date,
                interval_stability=interval_stability,
                amount_stability=amount_stability,
                confidence=confidence,
            )
        )
    return tuple(candidates)


def detect_price_increases(
    series: Iterable[RecurringSeriesCandidate],
    *,
    confirmed_series_fingerprints: Collection[str] = (),
    percent_threshold: Decimal = Decimal("5"),
    minimum_base_increase: Decimal = Decimal("1.00"),
    minimum_increase_by_currency: Mapping[str, Decimal] | None = None,
) -> tuple[PriceIncrease, ...]:
    """Compare the latest recurring price with a prior stable median."""

    if percent_threshold < 0 or minimum_base_increase < 0:
        raise ValueError("price-increase thresholds must not be negative")
    currency_minimums = {
        key.upper(): value for key, value in (minimum_increase_by_currency or {}).items()
    }
    if any(value < 0 for value in currency_minimums.values()):
        raise ValueError("currency minimums must not be negative")
    findings: list[PriceIncrease] = []
    for candidate in series:
        occurrences = candidate.occurrences
        if candidate.cadence is RecurringCadence.ANNUAL:
            if len(occurrences) < 2:
                continue
            if (
                len(occurrences) == 2
                and candidate.detector_fingerprint not in confirmed_series_fingerprints
            ):
                continue
        elif len(occurrences) < 4:
            continue

        prior = occurrences[:-1]
        latest = occurrences[-1]
        prior_amounts = [occurrence.comparison_amount for occurrence in prior]
        previous_median = _median(prior_amounts)
        if previous_median <= 0:
            continue
        if candidate.cadence is not RecurringCadence.ANNUAL and any(
            abs(amount - previous_median) > previous_median * Decimal("0.05")
            for amount in prior_amounts
        ):
            continue

        increase = latest.comparison_amount - previous_median
        if increase <= 0:
            continue
        increase_percent = (increase / previous_median * ONE_HUNDRED).quantize(RATIO_QUANTUM)
        if increase_percent < percent_threshold:
            continue

        prior_base = [occurrence.base_amount for occurrence in prior]
        increase_base: Decimal | None = None
        if latest.base_amount is not None and all(amount is not None for amount in prior_base):
            concrete_prior_base = [amount for amount in prior_base if amount is not None]
            increase_base = latest.base_amount - _median(concrete_prior_base)
            if increase_base < minimum_base_increase:
                continue
        else:
            if candidate.comparison_currency == "CAD":
                minimum = currency_minimums.get("CAD", minimum_base_increase)
            elif candidate.comparison_currency in currency_minimums:
                minimum = currency_minimums[candidate.comparison_currency]
            else:
                # A native threshold cannot be called CAD-equivalent without a
                # current valuation or an explicit currency-specific materiality.
                continue
            if increase < minimum:
                continue

        findings.append(
            PriceIncrease(
                series_fingerprint=candidate.detector_fingerprint,
                latest_transaction_id=latest.transaction_id,
                comparison_currency=candidate.comparison_currency,
                previous_median=previous_median,
                latest_amount=latest.comparison_amount,
                increase_amount=increase,
                increase_percent=increase_percent,
                increase_base=increase_base,
            )
        )
    return tuple(findings)


def detect_amount_anomalies(
    transactions: Iterable[AnalyticsTransaction],
    *,
    sensitivity: Sensitivity = Sensitivity.BALANCED,
    minimum_prior_observations: int = 5,
) -> tuple[AmountAnomaly, ...]:
    """Detect merchant-and-flow amount outliers using historical observations only."""

    if minimum_prior_observations < 2:
        raise ValueError("minimum_prior_observations must be at least two")
    profile = _SENSITIVITY[sensitivity]
    groups: dict[tuple[str, AnalyticsFlow], list[AnalyticsTransaction]] = defaultdict(list)
    for transaction in transactions:
        if (
            transaction.merchant_key is not None
            and transaction.amount_base is not None
            and transaction.flow_type not in {AnalyticsFlow.TRANSFER, AnalyticsFlow.REFUND}
        ):
            groups[(transaction.merchant_key, transaction.flow_type)].append(transaction)

    anomalies: list[AmountAnomaly] = []
    for (merchant_key, flow_type), group in sorted(
        groups.items(), key=lambda item: (item[0][0], item[0][1].value)
    ):
        prior_values: list[Decimal] = []
        for transaction in sorted(
            group, key=lambda item: (item.booked_date, item.transaction_id)
        ):
            assert transaction.amount_base is not None
            current = abs(transaction.amount_base)
            if len(prior_values) >= minimum_prior_observations:
                anomaly = _amount_anomaly(
                    transaction=transaction,
                    merchant_key=merchant_key,
                    flow_type=flow_type,
                    current=current,
                    prior_values=prior_values,
                    profile=profile,
                )
                if anomaly is not None:
                    anomalies.append(anomaly)
            prior_values.append(current)
    return tuple(anomalies)


def detect_unusual_frequency(
    transactions: Iterable[AnalyticsTransaction],
    *,
    as_of: date,
    sensitivity: Sensitivity = Sensitivity.BALANCED,
    minimum_prior_months: int = 5,
) -> tuple[FrequencyAnomaly, ...]:
    """Detect unusually high merchant frequency from complete calendar months."""

    if minimum_prior_months < 2:
        raise ValueError("minimum_prior_months must be at least two")
    profile = _SENSITIVITY[sensitivity]
    minimum_count_difference = {
        Sensitivity.LOW: Decimal("3"),
        Sensitivity.BALANCED: Decimal("2"),
        Sensitivity.HIGH: Decimal("1"),
    }[sensitivity]
    current_month = _month_start(as_of)
    grouped: dict[tuple[str, AnalyticsFlow], dict[date, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for transaction in transactions:
        if (
            transaction.merchant_key is None
            or transaction.flow_type in {AnalyticsFlow.TRANSFER, AnalyticsFlow.REFUND}
            or _month_start(transaction.booked_date) >= current_month
        ):
            continue
        grouped[(transaction.merchant_key, transaction.flow_type)][
            _month_start(transaction.booked_date)
        ] += 1

    anomalies: list[FrequencyAnomaly] = []
    for (merchant_key, flow_type), counts in sorted(
        grouped.items(), key=lambda item: (item[0][0], item[0][1].value)
    ):
        first_month = min(counts)
        last_month = max(counts)
        prior: list[Decimal] = []
        for period_start in _month_range(first_month, last_month):
            current = Decimal(counts.get(period_start, 0))
            if len(prior) >= minimum_prior_months:
                outlier = _high_outlier(
                    current=current,
                    prior_values=prior,
                    profile=profile,
                    minimum_difference=minimum_count_difference,
                )
                if outlier is not None:
                    baseline, difference, method, score = outlier
                    anomalies.append(
                        FrequencyAnomaly(
                            merchant_key=merchant_key,
                            flow_type=flow_type,
                            period_start=period_start,
                            transaction_count=int(current),
                            baseline_median=baseline,
                            count_difference=difference,
                            method=method,
                            score=score,
                            prior_month_count=len(prior),
                        )
                    )
            prior.append(current)
    return tuple(anomalies)


def detect_monthly_spikes(
    transactions: Iterable[AnalyticsTransaction],
    *,
    as_of: date,
    sensitivity: Sensitivity = Sensitivity.BALANCED,
    minimum_prior_months: int = 5,
) -> tuple[MonthlySpike, ...]:
    """Detect high category and merchant spend using complete valued prior months."""

    if minimum_prior_months < 2:
        raise ValueError("minimum_prior_months must be at least two")
    current_month = _month_start(as_of)
    globally_partial_months: set[date] = set()
    grouped: dict[
        tuple[AggregateDimension, str],
        dict[date, _MonthAccumulator],
    ] = defaultdict(dict)
    for transaction in transactions:
        period_start = _month_start(transaction.booked_date)
        if period_start >= current_month:
            continue
        if transaction.amount_base is None:
            globally_partial_months.add(period_start)
        dimensions: list[tuple[AggregateDimension, str]] = []
        if transaction.category_id is not None:
            dimensions.append((AggregateDimension.CATEGORY, transaction.category_id))
        if transaction.merchant_id is not None:
            dimensions.append((AggregateDimension.MERCHANT, transaction.merchant_id))
        for dimension in dimensions:
            accumulator = grouped[dimension].setdefault(period_start, _MonthAccumulator())
            accumulator.add(transaction)

    profile = _SENSITIVITY[sensitivity]
    spikes: list[MonthlySpike] = []
    for (dimension_type, dimension_key), months in sorted(
        grouped.items(), key=lambda item: (item[0][0].value, item[0][1])
    ):
        first_month = min(months)
        last_month = max(months)
        prior_complete: list[Decimal] = []
        for period_start in _month_range(first_month, last_month):
            if period_start in globally_partial_months:
                continue
            accumulator = months.get(period_start, _MonthAccumulator())
            result = accumulator.result()
            spending = result[2]
            coverage = result[8]
            if coverage is not CoverageStatus.COMPLETE:
                continue
            if len(prior_complete) >= minimum_prior_months:
                outlier = _high_outlier(
                    current=spending,
                    prior_values=prior_complete,
                    profile=profile,
                    minimum_difference=profile.minimum_difference_base,
                )
                if outlier is not None:
                    baseline, difference, method, score = outlier
                    spikes.append(
                        MonthlySpike(
                            dimension_type=dimension_type,
                            dimension_key=dimension_key,
                            period_start=period_start,
                            spending_base=spending,
                            baseline_median=baseline,
                            difference_base=difference,
                            method=method,
                            score=score,
                            prior_month_count=len(prior_complete),
                        )
                    )
            prior_complete.append(spending)
    return tuple(spikes)


def detect_near_duplicates(
    transactions: Iterable[AnalyticsTransaction],
    *,
    window_days: int = 3,
) -> tuple[NearDuplicate, ...]:
    """Find distinct same-account posted charges within an inclusive date window."""

    if window_days < 0:
        raise ValueError("window_days must not be negative")
    groups: dict[tuple[str, str, str, Decimal], list[AnalyticsTransaction]] = defaultdict(list)
    for transaction in transactions:
        if (
            transaction.merchant_key is None
            or transaction.is_reversal
            or transaction.flow_type is not AnalyticsFlow.SPEND
            or transaction.direction in {"payment", "refund"}
        ):
            continue
        key = (
            transaction.account_id,
            transaction.merchant_key,
            transaction.currency_native,
            abs(transaction.amount_native),
        )
        groups[key].append(transaction)

    duplicates: list[NearDuplicate] = []
    for (account_id, merchant_key, currency, amount), group in sorted(
        groups.items(), key=lambda item: (item[0][0], item[0][1], item[0][2], item[0][3])
    ):
        ordered = sorted(group, key=lambda item: (item.booked_date, item.transaction_id))
        for index, first in enumerate(ordered):
            for second in ordered[index + 1 :]:
                days_apart = (second.booked_date - first.booked_date).days
                if days_apart > window_days:
                    break
                if first.transaction_id == second.transaction_id:
                    continue
                duplicates.append(
                    NearDuplicate(
                        detector_fingerprint=_fingerprint(
                            "near_duplicate",
                            first.transaction_id,
                            second.transaction_id,
                            account_id,
                            merchant_key,
                            currency,
                            str(amount),
                            str(days_apart),
                        ),
                        first_transaction_id=first.transaction_id,
                        second_transaction_id=second.transaction_id,
                        account_id=account_id,
                        merchant_key=merchant_key,
                        currency_native=currency,
                        amount_native=amount,
                        days_apart=days_apart,
                    )
                )
    return tuple(duplicates)


class AnalyticsRefreshService:
    """Callable ``analytics_refresh`` job handler."""

    def __init__(
        self,
        *,
        repository: AnalyticsRefreshRepository,
        today: Callable[[], date] = date.today,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.repository = repository
        self.today = today
        self.clock = clock

    def run(self, payload: dict[str, object]) -> dict[str, object]:
        mode, requested_run_id = _analytics_refresh_payload(payload)
        started = self.clock()
        snapshot: AnalyticsSnapshot | None = None
        try:
            snapshot = self.repository.prepare_run(mode=mode, run_id=requested_run_id)
            analysis_date = self.today()
            aggregate_transactions = (
                snapshot.aggregate_transactions
                if snapshot.aggregate_transactions is not None
                else snapshot.transactions
            )
            aggregates = tuple(
                aggregate
                for aggregate in calculate_monthly_aggregates(aggregate_transactions)
                if not snapshot.affected_periods
                or aggregate.period_start in snapshot.affected_periods
            )
            recurring = detect_recurring_series(snapshot.transactions, as_of=analysis_date)
            findings = build_insight_findings(
                snapshot,
                recurring_series=recurring,
                as_of=analysis_date,
            )
            duration_ms = max(0, int((self.clock() - started) * 1000))
            result: dict[str, object] = {
                "generation": snapshot.context.generation,
                "mode": snapshot.context.mode,
                "source_watermark": (
                    snapshot.context.source_watermark.isoformat()
                    if snapshot.context.source_watermark is not None
                    else None
                ),
                "aggregate_count": len(aggregates),
                "recurring_series_count": len(recurring),
                "finding_count": len(findings),
                "duration_ms": duration_ms,
                "affected_periods": [
                    period.isoformat() for period in snapshot.affected_periods
                ],
            }
            self.repository.publish_run(
                snapshot=snapshot,
                aggregates=aggregates,
                recurring_series=recurring,
                findings=findings,
                result=result,
            )
            return result
        except Exception as error:
            failed_run_id = (
                snapshot.context.run_id if snapshot is not None else requested_run_id
            )
            if failed_run_id is not None:
                try:
                    self.repository.fail_run(
                        run_id=failed_run_id,
                        error=str(error) or error.__class__.__name__,
                    )
                except Exception as status_error:
                    error.add_note(
                        "analytics run failure status could not be persisted: "
                        f"{status_error}"
                    )
            raise


def build_insight_findings(
    snapshot: AnalyticsSnapshot,
    *,
    recurring_series: Sequence[RecurringSeriesCandidate],
    as_of: date,
) -> tuple[InsightFindingCandidate, ...]:
    """Build the finding types currently owned by the deterministic worker."""

    transactions = {
        transaction.transaction_id: transaction for transaction in snapshot.transactions
    }
    findings: dict[str, InsightFindingCandidate] = {
        finding.detector_fingerprint: finding for finding in snapshot.source_findings
    }
    review_by_fingerprint = {
        state.detector_fingerprint: state for state in snapshot.recurring_review_states
    }
    inactive_series = {
        fingerprint
        for fingerprint, state in review_by_fingerprint.items()
        if state.status in {"cancelled", "ignored"}
    }
    sensitivity_profile = _SENSITIVITY[snapshot.context.sensitivity]
    for amount_anomaly in detect_amount_anomalies(
        snapshot.transactions,
        sensitivity=snapshot.context.sensitivity,
    ):
        transaction = transactions[amount_anomaly.transaction_id]
        fingerprint = _fingerprint(
            FindingType.UNUSUAL_AMOUNT.value,
            amount_anomaly.transaction_id,
            str(amount_anomaly.amount_base),
            str(amount_anomaly.baseline_median),
            str(amount_anomaly.deviation_base),
            amount_anomaly.method.value,
        )
        findings[fingerprint] = InsightFindingCandidate(
            detector_fingerprint=fingerprint,
            finding_type=FindingType.UNUSUAL_AMOUNT,
            severity=FindingSeverity.WARNING,
            headline="Unusual transaction amount",
            account_id=transaction.account_id,
            transaction_id=amount_anomaly.transaction_id,
            evidence={
                "amountBase": str(amount_anomaly.amount_base),
                "baselineMedian": str(amount_anomaly.baseline_median),
                "deviationBase": str(amount_anomaly.deviation_base),
                "method": amount_anomaly.method.value,
                "score": (
                    str(amount_anomaly.score) if amount_anomaly.score is not None else None
                ),
                "priorObservationCount": amount_anomaly.prior_observation_count,
                "comparisonBasis": "CAD reporting amount magnitude",
                "modifiedZThreshold": str(sensitivity_profile.modified_z_threshold),
                "iqrMultiplier": str(sensitivity_profile.iqr_multiplier),
                "minimumDifferenceBase": str(
                    sensitivity_profile.minimum_difference_base
                ),
                "formula": (
                    "0.6745 * (amount - median) / medianAbsoluteDeviation"
                    if amount_anomaly.method is AnomalyMethod.MAD
                    else "outside Tukey fences derived from quartiles and IQR"
                ),
            },
        )
    for frequency_anomaly in detect_unusual_frequency(
        snapshot.transactions,
        as_of=as_of,
        sensitivity=snapshot.context.sensitivity,
    ):
        fingerprint = _fingerprint(
            FindingType.UNUSUAL_FREQUENCY.value,
            frequency_anomaly.merchant_key,
            frequency_anomaly.flow_type.value,
            frequency_anomaly.period_start.isoformat(),
            str(frequency_anomaly.transaction_count),
            str(frequency_anomaly.baseline_median),
        )
        findings[fingerprint] = InsightFindingCandidate(
            detector_fingerprint=fingerprint,
            finding_type=FindingType.UNUSUAL_FREQUENCY,
            severity=FindingSeverity.WARNING,
            headline="Unusual transaction frequency",
            evidence={
                "merchantKey": frequency_anomaly.merchant_key,
                "flowType": frequency_anomaly.flow_type.value,
                "periodStart": frequency_anomaly.period_start.isoformat(),
                "transactionCount": frequency_anomaly.transaction_count,
                "baselineMedian": str(frequency_anomaly.baseline_median),
                "countDifference": str(frequency_anomaly.count_difference),
                "method": frequency_anomaly.method.value,
                "score": (
                    str(frequency_anomaly.score)
                    if frequency_anomaly.score is not None
                    else None
                ),
                "priorMonthCount": frequency_anomaly.prior_month_count,
                "comparisonBasis": "complete calendar month transaction count",
                "modifiedZThreshold": str(sensitivity_profile.modified_z_threshold),
                "iqrMultiplier": str(sensitivity_profile.iqr_multiplier),
                "minimumCountDifference": str(
                    {
                        Sensitivity.LOW: Decimal("3"),
                        Sensitivity.BALANCED: Decimal("2"),
                        Sensitivity.HIGH: Decimal("1"),
                    }[snapshot.context.sensitivity]
                ),
                "formula": (
                    "0.6745 * (count - median) / medianAbsoluteDeviation"
                    if frequency_anomaly.method is AnomalyMethod.MAD
                    else "above the Tukey upper fence derived from quartiles and IQR"
                ),
            },
        )
    for spike in detect_monthly_spikes(
        snapshot.transactions,
        as_of=as_of,
        sensitivity=snapshot.context.sensitivity,
    ):
        fingerprint = _fingerprint(
            FindingType.MONTHLY_SPIKE.value,
            spike.dimension_type.value,
            spike.dimension_key,
            spike.period_start.isoformat(),
            str(spike.spending_base),
            str(spike.baseline_median),
        )
        findings[fingerprint] = InsightFindingCandidate(
            detector_fingerprint=fingerprint,
            finding_type=FindingType.MONTHLY_SPIKE,
            severity=FindingSeverity.WARNING,
            headline=f"Monthly {spike.dimension_type.value} spending spike",
            evidence={
                "dimensionType": spike.dimension_type.value,
                "dimensionId": spike.dimension_key,
                "periodStart": spike.period_start.isoformat(),
                "spendingBase": str(spike.spending_base),
                "baselineMedian": str(spike.baseline_median),
                "differenceBase": str(spike.difference_base),
                "method": spike.method.value,
                "score": str(spike.score) if spike.score is not None else None,
                "priorMonthCount": spike.prior_month_count,
                "comparisonBasis": "complete valued CAD calendar months",
                "modifiedZThreshold": str(sensitivity_profile.modified_z_threshold),
                "iqrMultiplier": str(sensitivity_profile.iqr_multiplier),
                "minimumDifferenceBase": str(
                    sensitivity_profile.minimum_difference_base
                ),
                "formula": (
                    "0.6745 * (spending - median) / medianAbsoluteDeviation"
                    if spike.method is AnomalyMethod.MAD
                    else "above the Tukey upper fence derived from quartiles and IQR"
                ),
            },
        )
    for duplicate in detect_near_duplicates(snapshot.transactions):
        second = transactions[duplicate.second_transaction_id]
        findings[duplicate.detector_fingerprint] = InsightFindingCandidate(
            detector_fingerprint=duplicate.detector_fingerprint,
            finding_type=FindingType.NEAR_DUPLICATE,
            severity=FindingSeverity.WARNING,
            headline="Possible duplicate charge",
            account_id=duplicate.account_id,
            transaction_id=duplicate.second_transaction_id,
            evidence={
                "firstTransactionId": duplicate.first_transaction_id,
                "secondTransactionId": duplicate.second_transaction_id,
                "merchantKey": duplicate.merchant_key,
                "amountNative": str(duplicate.amount_native),
                "currencyNative": duplicate.currency_native,
                "daysApart": duplicate.days_apart,
                "windowDays": 3,
                "comparisonBasis": "same account, merchant, posted currency and amount",
                "secondBookedDate": second.booked_date.isoformat(),
            },
        )
    for increase in detect_price_increases(
        [
            series
            for series in recurring_series
            if series.detector_fingerprint not in inactive_series
        ],
        confirmed_series_fingerprints={
            fingerprint
            for fingerprint, state in review_by_fingerprint.items()
            if state.status == "confirmed"
        },
    ):
        review = review_by_fingerprint.get(increase.series_fingerprint)
        if (
            review is not None
            and review.expected_amount_override is not None
            and increase.latest_amount <= review.expected_amount_override
        ):
            continue
        transaction = transactions[increase.latest_transaction_id]
        fingerprint = _fingerprint(
            FindingType.RECURRING_PRICE_INCREASE.value,
            increase.series_fingerprint,
            increase.latest_transaction_id,
            str(increase.previous_median),
            str(increase.latest_amount),
        )
        findings[fingerprint] = InsightFindingCandidate(
            detector_fingerprint=fingerprint,
            finding_type=FindingType.RECURRING_PRICE_INCREASE,
            severity=FindingSeverity.WARNING,
            headline="Recurring price increased",
            account_id=transaction.account_id,
            transaction_id=increase.latest_transaction_id,
            recurring_series_fingerprint=increase.series_fingerprint,
            evidence={
                "previousMedian": str(increase.previous_median),
                "latestAmount": str(increase.latest_amount),
                "increaseAmount": str(increase.increase_amount),
                "increasePercent": str(increase.increase_percent),
                "comparisonCurrency": increase.comparison_currency,
                "increaseBase": (
                    str(increase.increase_base) if increase.increase_base is not None else None
                ),
                "percentThreshold": "5",
                "minimumIncreaseBase": "1.00",
                "formula": "(latestAmount - previousMedian) / previousMedian * 100",
            },
        )
    for series in recurring_series:
        if series.detector_fingerprint in inactive_series:
            continue
        latest = series.occurrences[-1]
        review = review_by_fingerprint.get(series.detector_fingerprint)
        effective_cadence = (
            review.cadence_override
            if review is not None and review.cadence_override is not None
            else series.cadence
        )
        if review is not None and review.next_date_override is not None:
            expected_next_date = review.next_date_override
        elif review is not None and review.cadence_override is not None:
            expected_next_date = latest.occurrence_date + timedelta(
                days=_CADENCE_TYPICAL_DAYS[effective_cadence]
            )
        else:
            expected_next_date = series.expected_next_date
        if as_of <= expected_next_date:
            continue
        transaction = transactions[latest.transaction_id]
        fingerprint = _fingerprint(
            FindingType.RECURRING_OVERDUE.value,
            series.detector_fingerprint,
            expected_next_date.isoformat(),
        )
        findings[fingerprint] = InsightFindingCandidate(
            detector_fingerprint=fingerprint,
            finding_type=FindingType.RECURRING_OVERDUE,
            severity=FindingSeverity.INFO,
            headline="Recurring transaction is overdue",
            account_id=transaction.account_id,
            transaction_id=latest.transaction_id,
            recurring_series_fingerprint=series.detector_fingerprint,
            evidence={
                "expectedNextDate": expected_next_date.isoformat(),
                "cadence": effective_cadence.value,
                "merchantKey": series.merchant_key,
                "formula": "asOfDate > expectedNextDate",
            },
        )
    for transaction in snapshot.transactions:
        if transaction.amount_base is not None:
            continue
        fingerprint = _fingerprint(
            FindingType.PENDING_FX.value,
            transaction.transaction_id,
            transaction.booked_date.isoformat(),
            str(transaction.amount_native),
            transaction.currency_native,
        )
        findings[fingerprint] = InsightFindingCandidate(
            detector_fingerprint=fingerprint,
            finding_type=FindingType.PENDING_FX,
            severity=FindingSeverity.INFO,
            headline="CAD valuation is pending",
            account_id=transaction.account_id,
            transaction_id=transaction.transaction_id,
            evidence={
                "bookedDate": transaction.booked_date.isoformat(),
                "amountNative": str(transaction.amount_native),
                "currencyNative": transaction.currency_native,
            },
        )
    return tuple(findings[key] for key in sorted(findings))


class PostgresAnalyticsRepository:
    """PostgreSQL snapshot and generation publisher for Phase 2 analytics."""

    _MANAGED_FINDING_TYPES = tuple(finding_type.value for finding_type in FindingType)

    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("database_url cannot be blank")
        self._database_url = database_url

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self._database_url, row_factory=dict_row)

    def prepare_run(self, *, mode: str, run_id: str | None) -> AnalyticsSnapshot:
        if mode not in {"full", "incremental"}:
            raise ValueError("analytics refresh mode must be full or incremental")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute(
                """
                SELECT settings.sensitivity, settings.published_generation,
                       published.source_watermark AS previous_watermark
                FROM analytics_settings AS settings
                LEFT JOIN analytics_run AS published
                  ON published.generation = settings.published_generation
                WHERE settings.singleton
                """
            )
            settings_row = cursor.fetchone()
            if settings_row is None:
                raise RuntimeError("analytics settings singleton is missing")
            previous_generation = (
                int(settings_row["published_generation"])
                if settings_row["published_generation"] is not None
                else None
            )
            previous_watermark = settings_row["previous_watermark"]
            effective_mode = (
                "incremental"
                if mode == "incremental" and previous_generation is not None
                else "full"
            )
            cursor.execute(
                """
                SELECT GREATEST(
                    (SELECT max(updated_at) FROM txn),
                    (SELECT max(updated_at) FROM statement)
                ) AS watermark
                """
            )
            watermark_row = cursor.fetchone()
            watermark = watermark_row["watermark"] if watermark_row is not None else None
            if run_id is None:
                cursor.execute(
                    """
                    INSERT INTO analytics_run (
                        mode, status, source_watermark, started_at
                    ) VALUES (%s, 'running', %s, now())
                    RETURNING id::text, generation
                    """,
                    (effective_mode, watermark),
                )
            else:
                cursor.execute(
                    """
                    UPDATE analytics_run
                    SET mode = %s, status = 'running', source_watermark = %s,
                        started_at = COALESCE(started_at, now()), finished_at = NULL,
                        result = NULL, error = NULL
                    WHERE id = %s
                      AND status IN ('queued', 'running', 'failed')
                    RETURNING id::text, generation
                    """,
                    (effective_mode, watermark, run_id),
                )
            run_row = cursor.fetchone()
            if run_row is None:
                raise ValueError("analytics run is missing or cannot be started")
            sensitivity = Sensitivity(str(settings_row["sensitivity"]))
            transactions = self._load_transactions(cursor)
            if effective_mode == "full":
                transaction_periods = {
                    _month_start(transaction.booked_date) for transaction in transactions
                }
                affected_periods = (
                    tuple(_month_range(min(transaction_periods), max(transaction_periods)))
                    if transaction_periods
                    else ()
                )
                aggregate_transactions = transactions
                previous_generation = None
            else:
                affected_periods = self._load_affected_periods(
                    cursor,
                    previous_watermark=(
                        previous_watermark
                        if isinstance(previous_watermark, datetime)
                        else None
                    ),
                    watermark=watermark if isinstance(watermark, datetime) else None,
                )
                affected_period_set = set(affected_periods)
                aggregate_transactions = tuple(
                    transaction
                    for transaction in transactions
                    if _month_start(transaction.booked_date) in affected_period_set
                )
            source_findings = self._load_source_findings(cursor)
            cursor.execute(
                """
                SELECT detector_fingerprint, status, cadence_override,
                       expected_amount_override, next_date_override
                FROM recurring_series
                """
            )
            recurring_review_states = tuple(
                RecurringReviewState(
                    detector_fingerprint=str(row["detector_fingerprint"]),
                    status=str(row["status"]),
                    cadence_override=(
                        RecurringCadence(str(row["cadence_override"]))
                        if row["cadence_override"] is not None
                        else None
                    ),
                    expected_amount_override=row["expected_amount_override"],
                    next_date_override=row["next_date_override"],
                )
                for row in cursor.fetchall()
            )

        context = AnalyticsRunContext(
            run_id=str(run_row["id"]),
            generation=int(run_row["generation"]),
            mode=effective_mode,
            sensitivity=sensitivity,
            source_watermark=watermark if isinstance(watermark, datetime) else None,
        )
        return AnalyticsSnapshot(
            context=context,
            transactions=transactions,
            aggregate_transactions=aggregate_transactions,
            affected_periods=affected_periods,
            previous_generation=previous_generation,
            source_findings=source_findings,
            recurring_review_states=recurring_review_states,
        )

    @staticmethod
    def _load_affected_periods(
        cursor: psycopg.Cursor[Any],
        *,
        previous_watermark: datetime | None,
        watermark: datetime | None,
    ) -> tuple[date, ...]:
        if previous_watermark is None:
            cursor.execute(
                "SELECT DISTINCT date_trunc('month', booked_date)::date AS period FROM txn"
            )
        else:
            cursor.execute(
                """
                SELECT DISTINCT date_trunc('month', booked_date)::date AS period
                FROM txn
                WHERE updated_at > %s
                  AND (%s IS NULL OR updated_at <= %s)
                """,
                (previous_watermark, watermark, watermark),
            )
        return tuple(sorted(row["period"] for row in cursor.fetchall()))

    @staticmethod
    def _load_transactions(cursor: psycopg.Cursor[Any]) -> tuple[AnalyticsTransaction, ...]:
        cursor.execute(
            """
            SELECT
                transaction.id::text AS transaction_id,
                transaction.account_id::text AS account_id,
                transaction.booked_date,
                transaction.amount_native,
                transaction.currency_native,
                transaction.amount_base,
                transaction.original_amount,
                transaction.original_currency,
                transaction.fx_fee_amount_native,
                transaction.direction,
                merchant.id::text AS merchant_id,
                merchant.normalized_key AS merchant_key,
                category.id::text AS category_id,
                account.kind AS account_kind,
                transaction.enrichment #>> '{categorization,flow_type}' AS enriched_flow,
                transaction.enrichment @> '{"is_reversal": true}'::jsonb AS is_reversal
            FROM txn AS transaction
            JOIN account ON account.id = transaction.account_id
            LEFT JOIN merchant ON merchant.id = transaction.merchant_id
            LEFT JOIN category ON category.id = transaction.category_id
            ORDER BY transaction.booked_date, transaction.id
            """
        )
        transactions: list[AnalyticsTransaction] = []
        for row in cursor.fetchall():
            transactions.append(
                AnalyticsTransaction(
                    transaction_id=str(row["transaction_id"]),
                    account_id=str(row["account_id"]),
                    booked_date=row["booked_date"],
                    flow_type=_row_flow(row),
                    amount_native=row["amount_native"],
                    currency_native=str(row["currency_native"]),
                    amount_base=row["amount_base"],
                    merchant_key=(
                        str(row["merchant_key"]) if row["merchant_key"] is not None else None
                    ),
                    merchant_id=(
                        str(row["merchant_id"]) if row["merchant_id"] is not None else None
                    ),
                    category_id=(
                        str(row["category_id"]) if row["category_id"] is not None else None
                    ),
                    original_amount=row["original_amount"],
                    original_currency=(
                        str(row["original_currency"])
                        if row["original_currency"] is not None
                        else None
                    ),
                    fx_fee_amount_native=row["fx_fee_amount_native"],
                    direction=str(row["direction"]),
                    is_reversal=bool(row["is_reversal"]),
                )
            )
        return tuple(transactions)

    @staticmethod
    def _load_source_findings(cursor: psycopg.Cursor[Any]) -> tuple[InsightFindingCandidate, ...]:
        cursor.execute(
            """
            WITH statement_totals AS (
                SELECT statement.id, statement.account_id,
                       statement.period_start, statement.period_end,
                       statement.opening_balance, statement.closing_balance,
                       statement.currency, statement.reconcile_status,
                       COALESCE(SUM(transaction.amount_native), 0) AS transaction_total
                FROM statement
                LEFT JOIN txn AS transaction
                  ON transaction.statement_id = statement.id
                GROUP BY statement.id
            ), ordered AS (
                SELECT statement_totals.*,
                       MAX(period_end) OVER (
                           PARTITION BY account_id
                           ORDER BY period_start, period_end, id
                           ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                       ) AS previous_covered_until
                FROM statement_totals
            )
            SELECT id::text, account_id::text, period_start, period_end,
                   opening_balance, closing_balance, currency, reconcile_status,
                   transaction_total, previous_covered_until
            FROM ordered
            WHERE reconcile_status = 'mismatch'
               OR period_start > previous_covered_until + 1
            ORDER BY account_id, period_start, id
            """
        )
        findings: list[InsightFindingCandidate] = []
        for row in cursor.fetchall():
            mismatch = str(row["reconcile_status"]) == "mismatch"
            statement_id = str(row["id"])
            account_id = str(row["account_id"])
            if mismatch:
                opening = row["opening_balance"]
                closing = row["closing_balance"]
                transaction_total = row["transaction_total"]
                calculated = opening + transaction_total if opening is not None else None
                difference = (
                    closing - calculated
                    if closing is not None and calculated is not None
                    else None
                )
                findings.append(
                    InsightFindingCandidate(
                        detector_fingerprint=_fingerprint(
                            FindingType.RECONCILIATION_MISMATCH.value,
                            statement_id,
                            str(opening),
                            str(transaction_total),
                            str(closing),
                            str(difference),
                        ),
                        finding_type=FindingType.RECONCILIATION_MISMATCH,
                        severity=FindingSeverity.CRITICAL,
                        headline="Statement does not reconcile",
                        account_id=account_id,
                        evidence={
                            "statementId": statement_id,
                            "periodStart": row["period_start"].isoformat(),
                            "periodEnd": row["period_end"].isoformat(),
                            "openingBalance": str(opening) if opening is not None else None,
                            "transactionTotal": str(transaction_total),
                            "calculatedClosing": (
                                str(calculated) if calculated is not None else None
                            ),
                            "reportedClosing": str(closing) if closing is not None else None,
                            "difference": str(difference) if difference is not None else None,
                            "currency": str(row["currency"]),
                            "formula": "openingBalance + transactionTotal = calculatedClosing",
                        },
                    )
                )
            previous_covered_until = row["previous_covered_until"]
            if (
                previous_covered_until is not None
                and row["period_start"] > previous_covered_until + timedelta(days=1)
            ):
                gap_start = previous_covered_until + timedelta(days=1)
                gap_end = row["period_start"] - timedelta(days=1)
                findings.append(
                    InsightFindingCandidate(
                        detector_fingerprint=_fingerprint(
                            FindingType.COVERAGE_GAP.value,
                            account_id,
                            gap_start.isoformat(),
                            gap_end.isoformat(),
                        ),
                        finding_type=FindingType.COVERAGE_GAP,
                        severity=FindingSeverity.WARNING,
                        headline="Statement coverage gap",
                        account_id=account_id,
                        evidence={
                            "followingStatementId": statement_id,
                            "gapStart": gap_start.isoformat(),
                            "gapEnd": gap_end.isoformat(),
                            "currency": str(row["currency"]),
                        },
                    )
                )
        return tuple(findings)

    def publish_run(
        self,
        *,
        snapshot: AnalyticsSnapshot,
        aggregates: Sequence[MonthlyAggregate],
        recurring_series: Sequence[RecurringSeriesCandidate],
        findings: Sequence[InsightFindingCandidate],
        result: Mapping[str, object],
    ) -> None:
        context = snapshot.context
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT generation
                FROM analytics_run
                WHERE id = %s AND status = 'running'
                FOR UPDATE
                """,
                (context.run_id,),
            )
            run_row = cursor.fetchone()
            if run_row is None or int(run_row["generation"]) != context.generation:
                raise RuntimeError("analytics run is no longer publishable")
            cursor.execute(
                "DELETE FROM analytics_monthly_aggregate WHERE generation = %s",
                (context.generation,),
            )
            if snapshot.previous_generation is not None:
                self._copy_unaffected_aggregates(
                    cursor,
                    source_generation=snapshot.previous_generation,
                    target_generation=context.generation,
                    affected_periods=snapshot.affected_periods,
                )
            self._insert_aggregates(cursor, context.generation, aggregates)
            series_ids = self._upsert_recurring_series(
                cursor,
                generation=context.generation,
                series=recurring_series,
            )
            self._replace_detected_occurrences(
                cursor,
                generation=context.generation,
                series=recurring_series,
                series_ids=series_ids,
            )
            cursor.execute(
                """
                DELETE FROM recurring_series
                WHERE status = 'detected'
                  AND last_detected_generation <> %s
                """,
                (context.generation,),
            )
            self._upsert_findings(
                cursor,
                generation=context.generation,
                findings=findings,
                series_ids=series_ids,
            )
            cursor.execute(
                """
                UPDATE insight_finding
                SET status = 'resolved', resolved_at = now(), updated_at = now()
                WHERE status IN ('new', 'confirmed')
                  AND last_detected_generation <> %s
                  AND finding_type = ANY(%s)
                """,
                (context.generation, list(self._MANAGED_FINDING_TYPES)),
            )
            cursor.execute(
                "SELECT publish_analytics_generation(%s, %s)",
                (context.run_id, Jsonb(dict(result))),
            )

    @staticmethod
    def _copy_unaffected_aggregates(
        cursor: psycopg.Cursor[Any],
        *,
        source_generation: int,
        target_generation: int,
        affected_periods: Sequence[date],
    ) -> None:
        cursor.execute(
            """
            INSERT INTO analytics_monthly_aggregate (
                generation, period_start, dimension_type,
                account_id, category_id, merchant_id, currency_base,
                inflow_base, outflow_base, spending_base, net_base,
                transaction_count, valued_count, pending_fx_count,
                pending_fx_by_currency, coverage_status
            )
            SELECT %s, period_start, dimension_type,
                   account_id, category_id, merchant_id, currency_base,
                   inflow_base, outflow_base, spending_base, net_base,
                   transaction_count, valued_count, pending_fx_count,
                   pending_fx_by_currency, coverage_status
            FROM analytics_monthly_aggregate
            WHERE generation = %s
              AND NOT (period_start = ANY(%s::date[]))
            """,
            (target_generation, source_generation, list(affected_periods)),
        )

    @staticmethod
    def _insert_aggregates(
        cursor: psycopg.Cursor[Any],
        generation: int,
        aggregates: Sequence[MonthlyAggregate],
    ) -> None:
        for aggregate in aggregates:
            account_id = (
                aggregate.dimension_key
                if aggregate.dimension_type is AggregateDimension.ACCOUNT
                else None
            )
            category_id = (
                aggregate.dimension_key
                if aggregate.dimension_type is AggregateDimension.CATEGORY
                else None
            )
            merchant_id = (
                aggregate.dimension_key
                if aggregate.dimension_type is AggregateDimension.MERCHANT
                else None
            )
            cursor.execute(
                """
                INSERT INTO analytics_monthly_aggregate (
                    generation, period_start, dimension_type,
                    account_id, category_id, merchant_id,
                    inflow_base, outflow_base, spending_base, net_base,
                    transaction_count, valued_count, pending_fx_count,
                    pending_fx_by_currency, coverage_status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    generation,
                    aggregate.period_start,
                    aggregate.dimension_type.value,
                    account_id,
                    category_id,
                    merchant_id,
                    aggregate.inflow_base,
                    aggregate.outflow_base,
                    aggregate.spending_base,
                    aggregate.net_base,
                    aggregate.transaction_count,
                    aggregate.valued_count,
                    aggregate.pending_fx_count,
                    Jsonb(dict(aggregate.pending_fx_by_currency)),
                    aggregate.coverage_status.value,
                ),
            )

    @staticmethod
    def _upsert_recurring_series(
        cursor: psycopg.Cursor[Any],
        *,
        generation: int,
        series: Sequence[RecurringSeriesCandidate],
    ) -> dict[str, str]:
        series_ids: dict[str, str] = {}
        for candidate in series:
            cursor.execute(
                """
                INSERT INTO recurring_series (
                    detector_fingerprint, merchant_id, merchant_key, flow_type,
                    detected_cadence, comparison_basis, comparison_currency,
                    detected_expected_amount, detected_next_date, confidence,
                    first_occurrence_date, latest_occurrence_date,
                    last_detected_generation
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (detector_fingerprint) DO UPDATE
                SET merchant_id = COALESCE(EXCLUDED.merchant_id, recurring_series.merchant_id),
                    merchant_key = EXCLUDED.merchant_key,
                    flow_type = EXCLUDED.flow_type,
                    detected_cadence = EXCLUDED.detected_cadence,
                    comparison_basis = EXCLUDED.comparison_basis,
                    comparison_currency = EXCLUDED.comparison_currency,
                    detected_expected_amount = EXCLUDED.detected_expected_amount,
                    detected_next_date = EXCLUDED.detected_next_date,
                    confidence = EXCLUDED.confidence,
                    first_occurrence_date = LEAST(
                        recurring_series.first_occurrence_date,
                        EXCLUDED.first_occurrence_date
                    ),
                    latest_occurrence_date = EXCLUDED.latest_occurrence_date,
                    last_detected_generation = EXCLUDED.last_detected_generation,
                    updated_at = now()
                RETURNING id::text
                """,
                (
                    candidate.detector_fingerprint,
                    candidate.merchant_id,
                    candidate.merchant_key,
                    candidate.flow_type.value,
                    candidate.cadence.value,
                    candidate.comparison_basis.value,
                    candidate.comparison_currency,
                    candidate.expected_amount,
                    candidate.expected_next_date,
                    candidate.confidence,
                    candidate.occurrences[0].occurrence_date,
                    candidate.occurrences[-1].occurrence_date,
                    generation,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("recurring series upsert did not return an id")
            series_ids[candidate.detector_fingerprint] = str(row["id"])
        return series_ids

    @staticmethod
    def _replace_detected_occurrences(
        cursor: psycopg.Cursor[Any],
        *,
        generation: int,
        series: Sequence[RecurringSeriesCandidate],
        series_ids: Mapping[str, str],
    ) -> None:
        current_series_ids = list(series_ids.values())
        if current_series_ids:
            cursor.execute(
                """
                DELETE FROM recurring_occurrence
                WHERE match_source = 'detected'
                  AND series_id = ANY(%s::uuid[])
                """,
                (current_series_ids,),
            )
        for candidate in series:
            series_id = series_ids[candidate.detector_fingerprint]
            for occurrence_number, occurrence in enumerate(candidate.occurrences, start=1):
                cursor.execute(
                    """
                    INSERT INTO recurring_occurrence (
                        series_id, transaction_id, occurrence_number,
                        occurrence_date, comparison_amount, comparison_currency,
                        comparison_basis, match_source, detected_generation
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'detected', %s)
                    ON CONFLICT (transaction_id) DO NOTHING
                    """,
                    (
                        series_id,
                        occurrence.transaction_id,
                        occurrence_number,
                        occurrence.occurrence_date,
                        occurrence.comparison_amount,
                        candidate.comparison_currency,
                        candidate.comparison_basis.value,
                        generation,
                    ),
                )

    @staticmethod
    def _upsert_findings(
        cursor: psycopg.Cursor[Any],
        *,
        generation: int,
        findings: Sequence[InsightFindingCandidate],
        series_ids: Mapping[str, str],
    ) -> None:
        for finding in findings:
            recurring_series_id = (
                series_ids.get(finding.recurring_series_fingerprint)
                if finding.recurring_series_fingerprint is not None
                else None
            )
            cursor.execute(
                """
                INSERT INTO insight_finding (
                    detector_fingerprint, finding_type, severity, headline, evidence,
                    account_id, transaction_id, recurring_series_id,
                    last_detected_generation
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (detector_fingerprint) DO UPDATE
                SET finding_type = EXCLUDED.finding_type,
                    severity = EXCLUDED.severity,
                    status = CASE
                        WHEN insight_finding.status = 'resolved' THEN 'new'
                        ELSE insight_finding.status
                    END,
                    headline = EXCLUDED.headline,
                    evidence = EXCLUDED.evidence,
                    account_id = EXCLUDED.account_id,
                    transaction_id = EXCLUDED.transaction_id,
                    recurring_series_id = EXCLUDED.recurring_series_id,
                    last_seen_at = now(),
                    last_detected_generation = EXCLUDED.last_detected_generation,
                    resolved_at = CASE
                        WHEN insight_finding.status = 'resolved' THEN NULL
                        ELSE insight_finding.resolved_at
                    END,
                    updated_at = now()
                """,
                (
                    finding.detector_fingerprint,
                    finding.finding_type.value,
                    finding.severity.value,
                    finding.headline,
                    Jsonb(dict(finding.evidence)),
                    finding.account_id,
                    finding.transaction_id,
                    recurring_series_id,
                    generation,
                ),
            )

    def fail_run(self, *, run_id: str, error: str) -> None:
        safe_error = error.strip()[:2000] or "analytics refresh failed"
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE analytics_run
                SET status = 'failed', started_at = COALESCE(started_at, now()),
                    finished_at = now(), result = NULL, error = %s
                WHERE id = %s AND status <> 'succeeded'
                """,
                (safe_error, run_id),
            )


def _amount_anomaly(
    *,
    transaction: AnalyticsTransaction,
    merchant_key: str,
    flow_type: AnalyticsFlow,
    current: Decimal,
    prior_values: Sequence[Decimal],
    profile: _SensitivityProfile,
) -> AmountAnomaly | None:
    baseline = _median(prior_values)
    deviation = current - baseline
    if abs(deviation) < profile.minimum_difference_base:
        return None

    absolute_deviations = [abs(value - baseline) for value in prior_values]
    mad = _median(absolute_deviations)
    if mad > 0:
        score = (Decimal("0.6745") * deviation / mad).quantize(RATIO_QUANTUM)
        if abs(score) < profile.modified_z_threshold:
            return None
        method = AnomalyMethod.MAD
    else:
        lower_quartile, upper_quartile = _quartiles(prior_values)
        iqr = upper_quartile - lower_quartile
        lower_bound = lower_quartile - profile.iqr_multiplier * iqr
        upper_bound = upper_quartile + profile.iqr_multiplier * iqr
        if lower_bound <= current <= upper_bound and iqr > 0:
            return None
        if iqr == 0 and current == baseline:
            return None
        method = AnomalyMethod.IQR
        if iqr > 0:
            distance = (
                current - upper_quartile
                if current > upper_quartile
                else current - lower_quartile
            )
            score = (distance / iqr).quantize(RATIO_QUANTUM)
        else:
            score = None

    assert transaction.amount_base is not None
    return AmountAnomaly(
        transaction_id=transaction.transaction_id,
        merchant_key=merchant_key,
        flow_type=flow_type,
        amount_base=transaction.amount_base,
        baseline_median=baseline,
        deviation_base=deviation,
        method=method,
        score=score,
        prior_observation_count=len(prior_values),
    )


def _high_outlier(
    *,
    current: Decimal,
    prior_values: Sequence[Decimal],
    profile: _SensitivityProfile,
    minimum_difference: Decimal,
) -> tuple[Decimal, Decimal, AnomalyMethod, Decimal | None] | None:
    baseline = _median(prior_values)
    difference = current - baseline
    if difference < minimum_difference:
        return None
    mad = _median([abs(value - baseline) for value in prior_values])
    if mad > 0:
        score = (Decimal("0.6745") * difference / mad).quantize(RATIO_QUANTUM)
        if score < profile.modified_z_threshold:
            return None
        return baseline, difference, AnomalyMethod.MAD, score
    lower_quartile, upper_quartile = _quartiles(prior_values)
    iqr = upper_quartile - lower_quartile
    if iqr == 0:
        return baseline, difference, AnomalyMethod.IQR, None
    upper_bound = upper_quartile + profile.iqr_multiplier * iqr
    if current <= upper_bound:
        return None
    score = ((current - upper_quartile) / iqr).quantize(RATIO_QUANTUM)
    return baseline, difference, AnomalyMethod.IQR, score


def _comparison_values(
    transactions: Sequence[AnalyticsTransaction],
) -> tuple[
    ComparisonBasis,
    str,
    tuple[RecurringOccurrenceCandidate, ...],
] | None:
    original_currencies = {
        transaction.original_currency
        for transaction in transactions
        if transaction.original_currency is not None
    }
    if len(original_currencies) == 1 and all(
        transaction.original_amount is not None for transaction in transactions
    ):
        currency = next(iter(original_currencies))
        assert currency is not None
        basis = ComparisonBasis.ORIGINAL
        amounts: list[Decimal] = []
        for transaction in transactions:
            assert transaction.original_amount is not None
            amounts.append(abs(transaction.original_amount))
    elif len({transaction.currency_native for transaction in transactions}) == 1:
        currency = transactions[0].currency_native
        basis = ComparisonBasis.NATIVE
        amounts = [_native_price(transaction) for transaction in transactions]
    elif all(transaction.amount_base is not None for transaction in transactions):
        currency = "CAD"
        basis = ComparisonBasis.BASE
        amounts = []
        for transaction in transactions:
            base_price = _base_price(transaction)
            assert base_price is not None
            amounts.append(base_price)
    else:
        return None

    if any(amount <= 0 for amount in amounts):
        return None
    occurrences = tuple(
        RecurringOccurrenceCandidate(
            transaction_id=transaction.transaction_id,
            occurrence_date=transaction.booked_date,
            comparison_amount=amount,
            base_amount=_base_price(transaction),
        )
        for transaction, amount in zip(transactions, amounts, strict=True)
    )
    return basis, currency, occurrences


def _native_price(transaction: AnalyticsTransaction) -> Decimal:
    amount = abs(transaction.amount_native)
    fee = abs(transaction.fx_fee_amount_native or Decimal("0"))
    return max(amount - fee, Decimal("0"))


def _base_price(transaction: AnalyticsTransaction) -> Decimal | None:
    if transaction.amount_base is None:
        return None
    amount = abs(transaction.amount_base)
    if transaction.fx_fee_amount_native is None or transaction.amount_native == 0:
        return amount
    native_magnitude = abs(transaction.amount_native)
    base_fee = abs(transaction.fx_fee_amount_native) * amount / native_magnitude
    return _money(max(amount - base_fee, Decimal("0")))


def _cadence(intervals: Sequence[int]) -> tuple[RecurringCadence, Decimal] | None:
    if not intervals or any(interval <= 0 for interval in intervals):
        return None
    ranked: list[tuple[int, RecurringCadence]] = []
    for cadence, (minimum, maximum) in _CADENCE_RANGES.items():
        matches = sum(minimum <= interval <= maximum for interval in intervals)
        ranked.append((matches, cadence))
    matches, cadence = max(
        ranked,
        key=lambda item: (item[0], -list(RecurringCadence).index(item[1])),
    )
    if matches * 4 < len(intervals) * 3:
        return None
    return cadence, _ratio(matches, len(intervals))


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _month_range(first: date, last: date) -> Iterator[date]:
    current = first
    while current <= last:
        yield current
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)


def _percentage_change(previous: Decimal | None, current: Decimal) -> Decimal | None:
    if previous is None or previous == 0:
        return None
    return ((current - previous) / abs(previous) * ONE_HUNDRED).quantize(RATIO_QUANTUM)


def _median(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("median requires at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return _money((ordered[middle - 1] + ordered[middle]) / Decimal("2"))


def _quartiles(values: Sequence[Decimal]) -> tuple[Decimal, Decimal]:
    if len(values) < 2:
        raise ValueError("quartiles require at least two values")
    ordered = sorted(values)
    middle = len(ordered) // 2
    lower = ordered[:middle]
    upper = ordered[middle:] if len(ordered) % 2 == 0 else ordered[middle + 1 :]
    return _median(lower), _median(upper)


def _ratio(numerator: int, denominator: int) -> Decimal:
    return (Decimal(numerator) / Decimal(denominator)).quantize(RATIO_QUANTUM)


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _require_money(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if value != value.quantize(MONEY_QUANTUM):
        raise ValueError(f"{field_name} must have at most two decimal places")


def _consistent_merchant_id(transactions: Sequence[AnalyticsTransaction]) -> str | None:
    merchant_ids = {
        transaction.merchant_id
        for transaction in transactions
        if transaction.merchant_id is not None
    }
    return next(iter(merchant_ids)) if len(merchant_ids) == 1 else None


def _analytics_refresh_payload(payload: Mapping[str, object]) -> tuple[str, str | None]:
    mode = payload.get("mode", "incremental")
    if not isinstance(mode, str) or mode not in {"full", "incremental"}:
        raise ValueError("analytics refresh mode must be full or incremental")
    raw_run_id = payload.get("analytics_run_id")
    if raw_run_id is None:
        return mode, None
    if not isinstance(raw_run_id, str) or not raw_run_id.strip():
        raise ValueError("analytics_run_id must be a non-empty string")
    return mode, raw_run_id


def _row_flow(row: Mapping[str, Any]) -> AnalyticsFlow:
    enriched = row.get("enriched_flow")
    if isinstance(enriched, str):
        try:
            return AnalyticsFlow(enriched)
        except ValueError:
            pass
    direction = str(row.get("direction", "")).casefold()
    if direction in {"fee", "interest"}:
        return AnalyticsFlow.FEE
    if direction == "payment":
        return AnalyticsFlow.TRANSFER
    if direction == "refund":
        return AnalyticsFlow.REFUND
    account_kind = str(row.get("account_kind", ""))
    amount = row.get("amount_native")
    if account_kind == "credit_card":
        if isinstance(amount, Decimal) and amount < 0:
            return AnalyticsFlow.REFUND
        return AnalyticsFlow.SPEND
    if isinstance(amount, Decimal) and amount > 0:
        return AnalyticsFlow.INCOME
    return AnalyticsFlow.SPEND


def _currency(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("currency must be a three-letter ISO-style code")
    return normalized


def _fingerprint(*parts: str) -> str:
    return sha256("\x1f".join(parts).encode()).hexdigest()
