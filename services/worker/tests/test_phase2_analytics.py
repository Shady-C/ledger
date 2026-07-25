from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from worker.analytics import (
    AggregateDimension,
    AnalyticsFlow,
    AnalyticsRefreshService,
    AnalyticsRunContext,
    AnalyticsSnapshot,
    AnalyticsThresholdProfile,
    AnalyticsTransaction,
    AnomalyMethod,
    ComparisonBasis,
    CoverageStatus,
    FindingSeverity,
    FindingType,
    InsightFindingCandidate,
    MarketScope,
    MonthlyAggregate,
    PostgresAnalyticsRepository,
    RecurringCadence,
    RecurringReviewState,
    RecurringSeriesCandidate,
    Sensitivity,
    build_insight_findings,
    calculate_monthly_aggregates,
    calculate_monthly_trends,
    detect_amount_anomalies,
    detect_monthly_spikes,
    detect_near_duplicates,
    detect_price_increases,
    detect_recurring_series,
    detect_unusual_frequency,
)


class _Unset:
    pass


_UNSET = _Unset()


def _transaction(
    transaction_id: str,
    booked_date: date,
    amount: str,
    *,
    flow: AnalyticsFlow = AnalyticsFlow.SPEND,
    merchant: str | None = "merchant",
    account: str = "account-1",
    native_currency: str = "CAD",
    base_amount: str | _Unset | None = _UNSET,
    merchant_id: str | None = "merchant-id",
    category_id: str | None = "category-id",
    original_amount: str | None = None,
    original_currency: str | None = None,
    fx_fee: str | None = None,
    direction: str | None = None,
    is_reversal: bool = False,
    market_code: str | None = None,
) -> AnalyticsTransaction:
    return AnalyticsTransaction(
        transaction_id=transaction_id,
        account_id=account,
        booked_date=booked_date,
        merchant_key=merchant,
        merchant_id=merchant_id,
        category_id=category_id,
        flow_type=flow,
        amount_native=Decimal(amount),
        currency_native=native_currency,
        amount_base=(
            Decimal(amount)
            if base_amount is _UNSET
            else Decimal(base_amount)
            if isinstance(base_amount, str)
            else None
        ),
        original_amount=Decimal(original_amount) if original_amount is not None else None,
        original_currency=original_currency,
        fx_fee_amount_native=Decimal(fx_fee) if fx_fee is not None else None,
        direction=direction,
        is_reversal=is_reversal,
        market_code=market_code,
    )


def _finding_suite_snapshot() -> AnalyticsSnapshot:
    amount_rows = [
        _transaction(
            f"amount-{month}",
            date(2026, month, 10),
            "10.00",
            merchant="spike merchant",
            merchant_id="spike-merchant-id",
            category_id="spike-category-id",
        )
        for month in range(1, 6)
    ]
    amount_rows.extend(
        _transaction(
            f"amount-june-{day}",
            date(2026, 6, day),
            "100.00",
            merchant="spike merchant",
            merchant_id="spike-merchant-id",
            category_id="spike-category-id",
        )
        for day in (10, 11, 12)
    )
    start = date(2026, 1, 5)
    recurring_rows = [
        _transaction(
            f"recurring-{index}",
            start + timedelta(days=30 * index),
            "10.00" if index < 3 else "11.00",
            merchant="subscription",
            merchant_id="subscription-merchant-id",
            category_id="subscription-category-id",
        )
        for index in range(4)
    ]
    pending = _transaction(
        "pending-fx",
        date(2026, 7, 20),
        "27000.00",
        native_currency="TZS",
        base_amount=None,
        merchant=None,
        merchant_id=None,
        category_id=None,
    )
    source_findings = (
        InsightFindingCandidate(
            detector_fingerprint="mismatch-fingerprint",
            finding_type=FindingType.RECONCILIATION_MISMATCH,
            severity=FindingSeverity.CRITICAL,
            headline="Statement does not reconcile",
            account_id="account-1",
            evidence={"difference": "5.00"},
        ),
        InsightFindingCandidate(
            detector_fingerprint="gap-fingerprint",
            finding_type=FindingType.COVERAGE_GAP,
            severity=FindingSeverity.WARNING,
            headline="Statement coverage gap",
            account_id="account-1",
            evidence={"gapStart": "2026-02-01", "gapEnd": "2026-02-02"},
        ),
    )
    return AnalyticsSnapshot(
        context=AnalyticsRunContext(
            run_id="run-1",
            generation=7,
            mode="full",
            sensitivity=Sensitivity.BALANCED,
            source_watermark=datetime(2026, 7, 31, 12, tzinfo=UTC),
        ),
        transactions=tuple([*amount_rows, *recurring_rows, pending]),
        source_findings=source_findings,
    )


def test_transaction_projection_requires_exact_money_and_currency_pairs() -> None:
    normalized = _transaction(
        "normalized",
        date(2026, 1, 1),
        "10.00",
        merchant="  ACME STORE ",
        native_currency="tzs",
        original_amount="4.00",
        original_currency=" usd ",
        direction=" FEE ",
    )

    assert normalized.merchant_key == "acme store"
    assert normalized.currency_native == "TZS"
    assert normalized.original_currency == "USD"
    assert normalized.direction == "fee"

    with pytest.raises(ValueError, match="present together"):
        AnalyticsTransaction(
            transaction_id="bad-pair",
            account_id="account",
            booked_date=date(2026, 1, 1),
            flow_type=AnalyticsFlow.SPEND,
            amount_native=Decimal("10.00"),
            currency_native="CAD",
            amount_base=Decimal("10.00"),
            original_amount=Decimal("5.00"),
        )
    with pytest.raises(ValueError, match="two decimal"):
        _transaction("bad-precision", date(2026, 1, 1), "1.001")
    with pytest.raises(TypeError, match="Decimal"):
        AnalyticsTransaction(
            transaction_id="bad-type",
            account_id="account",
            booked_date=date(2026, 1, 1),
            flow_type=AnalyticsFlow.SPEND,
            amount_native=10,  # type: ignore[arg-type]
            currency_native="CAD",
            amount_base=Decimal("10.00"),
        )


def test_monthly_trends_are_gap_filled_exact_and_partial_aware() -> None:
    january = date(2026, 1, 4)
    rows = [
        _transaction("income", january, "1000.00", flow=AnalyticsFlow.INCOME),
        _transaction("spend", january, "200.00"),
        _transaction("fee", january, "10.00", flow=AnalyticsFlow.FEE),
        _transaction("refund", january, "-20.00", flow=AnalyticsFlow.REFUND),
        _transaction("transfer", january, "500.00", flow=AnalyticsFlow.TRANSFER),
        _transaction(
            "pending-tzs",
            january,
            "27000.00",
            native_currency="TZS",
            base_amount=None,
        ),
        _transaction(
            "pending-usd",
            january,
            "20.00",
            native_currency="USD",
            base_amount=None,
        ),
        _transaction("march", date(2026, 3, 2), "300.00"),
    ]
    trends = calculate_monthly_trends(rows)

    assert [trend.period_start for trend in trends] == [
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
    ]
    january_result, february_result, march_result = trends
    assert (
        january_result.inflow_base,
        january_result.outflow_base,
        january_result.spending_base,
        january_result.net_base,
    ) == (Decimal("1000.00"), Decimal("190.00"), Decimal("190.00"), Decimal("810.00"))
    assert january_result.transaction_count == 7
    assert january_result.valued_count == 5
    assert january_result.pending_fx_count == 2
    assert january_result.pending_fx_by_currency == (("TZS", 1), ("USD", 1))
    assert january_result.coverage_status is CoverageStatus.PARTIAL
    assert february_result.transaction_count == 0
    assert february_result.coverage_status is CoverageStatus.COMPLETE
    assert february_result.spending_change_from_previous == Decimal("-190.00")
    assert february_result.spending_change_percent == Decimal("-100.0000")
    assert march_result.spending_change_from_previous == Decimal("300.00")
    assert march_result.spending_change_percent is None
    assert march_result.trailing_three_month_average == Decimal("163.33")
    assert march_result.trailing_three_month_median == Decimal("190.00")


def test_monthly_trends_compute_year_over_year_changes() -> None:
    trends = calculate_monthly_trends(
        [
            _transaction("old", date(2025, 1, 2), "100.00"),
            _transaction("new", date(2026, 1, 2), "125.00"),
        ]
    )

    january_2026 = trends[-1]
    assert january_2026.spending_change_from_previous_year == Decimal("25.00")
    assert january_2026.spending_change_from_previous_year_percent == Decimal("25.0000")


def test_monthly_materialization_builds_all_available_dimensions() -> None:
    transaction = _transaction("one", date(2026, 2, 2), "15.00")

    aggregates = calculate_monthly_aggregates([transaction])

    assert [(row.dimension_type, row.dimension_key) for row in aggregates] == [
        (AggregateDimension.ACCOUNT, "account-1"),
        (AggregateDimension.CATEGORY, "category-id"),
        (AggregateDimension.LEDGER, None),
        (AggregateDimension.MERCHANT, "merchant-id"),
    ]
    assert all(row.spending_base == Decimal("15.00") for row in aggregates)
    assert all(row.coverage_status is CoverageStatus.COMPLETE for row in aggregates)


@pytest.mark.parametrize(
    ("cadence", "interval_days", "count"),
    [
        (RecurringCadence.WEEKLY, 7, 3),
        (RecurringCadence.BIWEEKLY, 14, 3),
        (RecurringCadence.MONTHLY, 30, 3),
        (RecurringCadence.QUARTERLY, 90, 3),
        (RecurringCadence.ANNUAL, 365, 2),
    ],
)
def test_recurring_detection_supports_every_planned_cadence(
    cadence: RecurringCadence, interval_days: int, count: int
) -> None:
    start = date(2024, 1, 1)
    rows = [
        _transaction(
            f"{cadence}-{index}",
            start + timedelta(days=interval_days * index),
            "20.00",
            merchant=cadence.value,
        )
        for index in range(count)
    ]

    detected = detect_recurring_series(rows, as_of=start)

    assert len(detected) == 1
    assert detected[0].cadence is cadence
    assert detected[0].interval_stability == Decimal("1.0000")
    assert detected[0].amount_stability == Decimal("1.0000")
    assert detected[0].confidence == Decimal("1.0000")
    assert detected[0].expected_next_date == rows[-1].booked_date + timedelta(days=interval_days)
    assert not detected[0].overdue


def test_recurring_comparison_prefers_original_then_native_then_base() -> None:
    start = date(2026, 1, 1)
    original_rows = [
        _transaction(
            f"original-{index}",
            start + timedelta(days=30 * index),
            "270000.00",
            base_amount="140.00",
            native_currency="TZS",
            merchant="original merchant",
            original_amount="100.00",
            original_currency="USD",
            fx_fee="5000.00",
        )
        for index in range(3)
    ]
    native_rows = [
        _transaction(
            f"native-{index}",
            start + timedelta(days=30 * index),
            "10.50",
            merchant="native merchant",
            fx_fee="0.50",
        )
        for index in range(3)
    ]
    base_rows = [
        _transaction(
            f"base-{index}",
            start + timedelta(days=30 * index),
            "10.00" if index % 2 == 0 else "13000.00",
            base_amount="14.00",
            native_currency="USD" if index % 2 == 0 else "TZS",
            merchant="base merchant",
        )
        for index in range(3)
    ]

    detected = {
        candidate.merchant_key: candidate
        for candidate in detect_recurring_series(original_rows + native_rows + base_rows)
    }

    assert detected["original merchant"].comparison_basis is ComparisonBasis.ORIGINAL
    assert detected["original merchant"].comparison_currency == "USD"
    assert detected["original merchant"].expected_amount == Decimal("100.00")
    assert detected["native merchant"].comparison_basis is ComparisonBasis.NATIVE
    assert detected["native merchant"].expected_amount == Decimal("10.00")
    assert detected["base merchant"].comparison_basis is ComparisonBasis.BASE
    assert detected["base merchant"].comparison_currency == "CAD"
    assert detected["base merchant"].expected_amount == Decimal("14.00")


def test_recurring_detection_rejects_unstable_intervals_and_non_cash_flows() -> None:
    start = date(2026, 1, 1)
    unstable = [
        _transaction("unstable-1", start, "10.00", merchant="unstable"),
        _transaction("unstable-2", start + timedelta(days=7), "10.00", merchant="unstable"),
        _transaction("unstable-3", start + timedelta(days=37), "10.00", merchant="unstable"),
    ]
    transfers = [
        _transaction(
            f"transfer-{index}",
            start + timedelta(days=index * 30),
            "10.00",
            merchant="transfer",
            flow=AnalyticsFlow.TRANSFER,
        )
        for index in range(3)
    ]

    assert detect_recurring_series(unstable + transfers) == ()


def test_recurring_overdue_and_inline_fee_price_increase() -> None:
    start = date(2026, 1, 1)
    rows = [
        _transaction(
            f"subscription-{index}",
            start + timedelta(days=30 * index),
            "10.50" if index < 3 else "11.50",
            base_amount="10.50" if index < 3 else "11.50",
            fx_fee="0.50",
            merchant="subscription",
        )
        for index in range(4)
    ]
    series = detect_recurring_series(rows, as_of=date(2026, 6, 1))

    assert series[0].overdue
    findings = detect_price_increases(series)
    assert len(findings) == 1
    assert findings[0].previous_median == Decimal("10.00")
    assert findings[0].latest_amount == Decimal("11.00")
    assert findings[0].increase_amount == Decimal("1.00")
    assert findings[0].increase_percent == Decimal("10.0000")
    assert findings[0].increase_base == Decimal("1.00")


def test_price_increase_requires_stable_history_and_materiality() -> None:
    start = date(2026, 1, 1)
    unstable_rows = [
        _transaction(
            f"unstable-price-{index}",
            start + timedelta(days=30 * index),
            amount,
            merchant="unstable price",
        )
        for index, amount in enumerate(["10.00", "20.00", "10.00", "30.00"])
    ]
    immaterial_rows = [
        _transaction(
            f"immaterial-{index}",
            start + timedelta(days=30 * index),
            "10.00" if index < 3 else "10.50",
            merchant="immaterial",
        )
        for index in range(4)
    ]

    candidates = detect_recurring_series(unstable_rows + immaterial_rows)

    assert detect_price_increases(candidates) == ()


def test_two_occurrence_annual_price_increase_requires_confirmation() -> None:
    rows = [
        _transaction("annual-old", date(2025, 1, 1), "100.00", merchant="annual"),
        _transaction("annual-new", date(2026, 1, 1), "110.00", merchant="annual"),
    ]
    series = detect_recurring_series(rows)

    assert len(series) == 1
    assert detect_price_increases(series) == ()
    confirmed = detect_price_increases(
        series,
        confirmed_series_fingerprints={series[0].detector_fingerprint},
    )
    assert confirmed[0].increase_percent == Decimal("10.0000")


def test_pending_non_cad_price_increase_requires_explicit_equivalent_threshold() -> None:
    start = date(2026, 1, 1)
    rows = [
        _transaction(
            f"tzs-{index}",
            start + timedelta(days=30 * index),
            "100.00" if index < 3 else "110.00",
            native_currency="TZS",
            base_amount=None,
            merchant="tzs subscription",
        )
        for index in range(4)
    ]
    series = detect_recurring_series(rows)

    assert detect_price_increases(series) == ()
    findings = detect_price_increases(
        series,
        minimum_increase_by_currency={"TZS": Decimal("5.00")},
    )
    assert findings[0].increase_amount == Decimal("10.00")


def test_amount_anomaly_uses_prior_mad_baseline() -> None:
    start = date(2026, 1, 1)
    rows = [
        _transaction(f"baseline-{index}", start + timedelta(days=index), amount)
        for index, amount in enumerate(["10.00", "11.00", "12.00", "13.00", "14.00"])
    ]
    rows.append(_transaction("outlier", start + timedelta(days=6), "100.00"))

    anomalies = detect_amount_anomalies(rows)

    assert len(anomalies) == 1
    assert anomalies[0].transaction_id == "outlier"
    assert anomalies[0].baseline_median == Decimal("12.00")
    assert anomalies[0].deviation_base == Decimal("88.00")
    assert anomalies[0].method is AnomalyMethod.MAD
    assert anomalies[0].score == Decimal("59.3560")
    assert anomalies[0].prior_observation_count == 5


def test_amount_anomaly_falls_back_to_iqr_when_mad_is_zero() -> None:
    start = date(2026, 1, 1)
    rows = [
        _transaction(f"iqr-{index}", start + timedelta(days=index), amount)
        for index, amount in enumerate(["10.00", "10.00", "10.00", "20.00", "20.00"])
    ]
    rows.append(_transaction("iqr-outlier", start + timedelta(days=6), "50.00"))

    anomaly = detect_amount_anomalies(rows)[0]

    assert anomaly.method is AnomalyMethod.IQR
    assert anomaly.score == Decimal("3.0000")


def test_amount_anomaly_zero_variance_and_sensitivity_thresholds() -> None:
    start = date(2026, 1, 1)
    baseline = [
        _transaction(f"same-{index}", start + timedelta(days=index), "10.00")
        for index in range(5)
    ]
    moderate = [*baseline, _transaction("moderate", start + timedelta(days=6), "30.00")]
    larger = [*baseline, _transaction("larger", start + timedelta(days=6), "35.00")]

    balanced = detect_amount_anomalies(moderate, sensitivity=Sensitivity.BALANCED)
    low = detect_amount_anomalies(moderate, sensitivity=Sensitivity.LOW)
    low_larger = detect_amount_anomalies(larger, sensitivity=Sensitivity.LOW)

    assert balanced[0].method is AnomalyMethod.IQR
    assert balanced[0].score is None
    assert low == ()
    assert low_larger[0].transaction_id == "larger"


def test_amount_anomaly_excludes_pending_refunds_and_transfers() -> None:
    start = date(2026, 1, 1)
    rows = [
        _transaction(f"base-{index}", start + timedelta(days=index), "10.00")
        for index in range(5)
    ]
    pending = _transaction("pending", start + timedelta(days=6), "100.00")
    pending = AnalyticsTransaction(
        transaction_id=pending.transaction_id,
        account_id=pending.account_id,
        booked_date=pending.booked_date,
        flow_type=pending.flow_type,
        amount_native=pending.amount_native,
        currency_native=pending.currency_native,
        amount_base=None,
        merchant_key=pending.merchant_key,
    )
    rows.extend(
        [
            pending,
            _transaction(
                "refund-outlier",
                start + timedelta(days=7),
                "100.00",
                flow=AnalyticsFlow.REFUND,
            ),
            _transaction(
                "transfer-outlier",
                start + timedelta(days=8),
                "100.00",
                flow=AnalyticsFlow.TRANSFER,
            ),
        ]
    )

    assert detect_amount_anomalies(rows) == ()


def test_unusual_frequency_uses_five_complete_prior_calendar_months() -> None:
    rows = [
        _transaction(f"baseline-{month}", date(2026, month, 10), "10.00")
        for month in range(1, 6)
    ]
    rows.extend(
        _transaction(f"june-{day}", date(2026, 6, day), "10.00")
        for day in (10, 11, 12)
    )

    anomalies = detect_unusual_frequency(rows, as_of=date(2026, 7, 1))

    assert len(anomalies) == 1
    assert anomalies[0].period_start == date(2026, 6, 1)
    assert anomalies[0].transaction_count == 3
    assert anomalies[0].baseline_median == Decimal("1")
    assert anomalies[0].count_difference == Decimal("2")
    assert anomalies[0].prior_month_count == 5
    assert detect_unusual_frequency(rows, as_of=date(2026, 6, 15)) == ()


def test_monthly_spikes_cover_category_and_merchant_and_skip_global_partial_months() -> None:
    complete_rows = [
        _transaction(f"baseline-{month}", date(2026, month, 10), "10.00")
        for month in range(1, 6)
    ]
    current = _transaction("spike", date(2026, 6, 10), "100.00")

    spikes = detect_monthly_spikes([*complete_rows, current], as_of=date(2026, 7, 1))

    assert {(spike.dimension_type, spike.dimension_key) for spike in spikes} == {
        (AggregateDimension.CATEGORY, "category-id"),
        (AggregateDimension.MERCHANT, "merchant-id"),
    }
    assert all(spike.baseline_median == Decimal("10.00") for spike in spikes)
    assert all(spike.difference_base == Decimal("90.00") for spike in spikes)

    unrelated_pending = _transaction(
        "pending",
        date(2026, 3, 15),
        "1000.00",
        native_currency="TZS",
        base_amount=None,
        merchant="other",
        merchant_id="other-merchant",
        category_id="other-category",
    )
    assert (
        detect_monthly_spikes(
            [*complete_rows, unrelated_pending, current],
            as_of=date(2026, 7, 1),
        )
        == ()
    )


def test_near_duplicates_require_same_posted_identity_and_inclusive_window() -> None:
    first = _transaction("first", date(2026, 1, 1), "20.00", merchant="ACME")
    second = _transaction("second", date(2026, 1, 4), "-20.00", merchant="acme")
    outside = _transaction("outside", date(2026, 1, 5), "20.00", merchant="acme")
    other_account = _transaction(
        "other-account", date(2026, 1, 2), "20.00", merchant="acme", account="account-2"
    )
    other_currency = _transaction(
        "other-currency",
        date(2026, 1, 2),
        "20.00",
        merchant="acme",
        native_currency="USD",
    )

    duplicates = detect_near_duplicates(
        [outside, second, other_account, first, other_currency]
    )

    assert len(duplicates) == 2
    assert (duplicates[0].first_transaction_id, duplicates[0].second_transaction_id) == (
        "first",
        "second",
    )
    assert duplicates[0].days_apart == 3
    assert duplicates[0].amount_native == Decimal("20.00")
    assert (duplicates[1].first_transaction_id, duplicates[1].second_transaction_id) == (
        "second",
        "outside",
    )


@pytest.mark.parametrize(
    "excluded",
    [
        {"flow": AnalyticsFlow.REFUND},
        {"flow": AnalyticsFlow.TRANSFER},
        {"flow": AnalyticsFlow.FEE},
        {"flow": AnalyticsFlow.INCOME},
        {"direction": "payment"},
        {"direction": "refund"},
        {"is_reversal": True},
    ],
)
def test_near_duplicates_exclude_non_charge_activity(excluded: dict[str, object]) -> None:
    first = _transaction("first", date(2026, 1, 1), "20.00")
    second = _transaction("second", date(2026, 1, 2), "20.00", **excluded)  # type: ignore[arg-type]

    assert detect_near_duplicates([first, second]) == ()


def test_near_duplicate_fingerprint_is_input_order_independent() -> None:
    first = _transaction("first", date(2026, 1, 1), "20.00")
    second = _transaction("second", date(2026, 1, 1), "20.00")

    forward = detect_near_duplicates([first, second])
    reverse = detect_near_duplicates([second, first])

    assert forward == reverse


def test_finding_builder_emits_complete_deterministic_suite_with_evidence() -> None:
    snapshot = _finding_suite_snapshot()
    recurring = detect_recurring_series(snapshot.transactions, as_of=date(2026, 8, 1))

    findings = build_insight_findings(
        snapshot,
        recurring_series=recurring,
        as_of=date(2026, 8, 1),
    )

    finding_types = {finding.finding_type for finding in findings}
    assert finding_types == set(FindingType)
    spike = next(
        finding for finding in findings if finding.finding_type is FindingType.MONTHLY_SPIKE
    )
    assert spike.evidence["dimensionType"] in {"category", "merchant"}
    assert spike.evidence["dimensionId"] in {
        "spike-category-id",
        "spike-merchant-id",
    }
    assert (
        spike.evidence["comparisonBasis"]
        == "complete valued home-currency calendar months"
    )
    duplicate = next(
        finding for finding in findings if finding.finding_type is FindingType.NEAR_DUPLICATE
    )
    assert duplicate.evidence["windowDays"] == 3
    anomaly = next(
        finding for finding in findings if finding.finding_type is FindingType.UNUSUAL_AMOUNT
    )
    assert anomaly.evidence["modifiedZThreshold"] == "3.5"
    assert "formula" in anomaly.evidence


def test_cancelled_recurring_series_suppresses_price_and_overdue_findings() -> None:
    snapshot = _finding_suite_snapshot()
    recurring = detect_recurring_series(snapshot.transactions, as_of=date(2026, 8, 1))
    subscription = next(series for series in recurring if series.merchant_key == "subscription")
    reviewed_snapshot = AnalyticsSnapshot(
        context=snapshot.context,
        transactions=snapshot.transactions,
        source_findings=snapshot.source_findings,
        recurring_review_states=(
            RecurringReviewState(
                detector_fingerprint=subscription.detector_fingerprint,
                status="cancelled",
            ),
        ),
    )

    findings = build_insight_findings(
        reviewed_snapshot,
        recurring_series=recurring,
        as_of=date(2026, 8, 1),
    )

    assert not any(
        finding.recurring_series_fingerprint == subscription.detector_fingerprint
        for finding in findings
    )


def test_confirmed_annual_series_and_user_overrides_control_findings() -> None:
    annual_rows = (
        _transaction("annual-1", date(2025, 1, 1), "100.00", merchant="annual"),
        _transaction("annual-2", date(2026, 1, 1), "110.00", merchant="annual"),
    )
    context = AnalyticsRunContext(
        run_id="annual-run",
        generation=2,
        mode="incremental",
        sensitivity=Sensitivity.BALANCED,
        source_watermark=None,
    )
    recurring = detect_recurring_series(annual_rows, as_of=date(2026, 7, 1))
    fingerprint = recurring[0].detector_fingerprint
    confirmed = AnalyticsSnapshot(
        context=context,
        transactions=annual_rows,
        recurring_review_states=(
            RecurringReviewState(detector_fingerprint=fingerprint, status="confirmed"),
        ),
    )

    findings = build_insight_findings(
        confirmed,
        recurring_series=recurring,
        as_of=date(2026, 7, 1),
    )
    assert any(
        finding.finding_type is FindingType.RECURRING_PRICE_INCREASE
        for finding in findings
    )

    accepted_price = AnalyticsSnapshot(
        context=context,
        transactions=annual_rows,
        recurring_review_states=(
            RecurringReviewState(
                detector_fingerprint=fingerprint,
                status="confirmed",
                cadence_override=RecurringCadence.ANNUAL,
                expected_amount_override=Decimal("110.00"),
                next_date_override=date(2027, 1, 15),
            ),
        ),
    )
    accepted_findings = build_insight_findings(
        accepted_price,
        recurring_series=recurring,
        as_of=date(2026, 7, 1),
    )
    assert not any(
        finding.finding_type
        in {FindingType.RECURRING_PRICE_INCREASE, FindingType.RECURRING_OVERDUE}
        for finding in accepted_findings
    )


class _MemoryAnalyticsRefreshRepository:
    def __init__(
        self,
        snapshot: AnalyticsSnapshot,
        *,
        fail_prepare: bool = False,
        fail_publish: bool = False,
    ) -> None:
        self.snapshot = snapshot
        self.fail_prepare = fail_prepare
        self.fail_publish = fail_publish
        self.prepared: tuple[str, str | None] | None = None
        self.published: tuple[
            AnalyticsSnapshot,
            tuple[MonthlyAggregate, ...],
            tuple[RecurringSeriesCandidate, ...],
            tuple[InsightFindingCandidate, ...],
            dict[str, object],
        ] | None = None
        self.failed: tuple[str, str] | None = None

    def prepare_run(self, *, mode: str, run_id: str | None) -> AnalyticsSnapshot:
        self.prepared = (mode, run_id)
        if self.fail_prepare:
            raise RuntimeError("snapshot failed")
        return self.snapshot

    def publish_run(
        self,
        *,
        snapshot: AnalyticsSnapshot,
        aggregates: tuple[MonthlyAggregate, ...],
        recurring_series: tuple[RecurringSeriesCandidate, ...],
        findings: tuple[InsightFindingCandidate, ...],
        result: dict[str, object],
    ) -> None:
        if self.fail_publish:
            raise RuntimeError("publication failed")
        self.published = (snapshot, aggregates, recurring_series, findings, result)

    def fail_run(self, *, run_id: str, error: str) -> None:
        self.failed = (run_id, error)


def test_analytics_refresh_service_materializes_and_publishes_only_at_completion() -> None:
    repository = _MemoryAnalyticsRefreshRepository(_finding_suite_snapshot())
    ticks = iter([10.0, 10.125])
    service = AnalyticsRefreshService(
        repository=repository,
        today=lambda: date(2026, 8, 1),
        clock=lambda: next(ticks),
    )

    result = service.run({"mode": "full", "analytics_run_id": "run-1"})

    assert repository.prepared == ("full", "run-1")
    assert repository.failed is None
    assert repository.published is not None
    assert result == repository.published[-1]
    assert result["generation"] == 7
    assert result["source_watermark"] == "2026-07-31T12:00:00+00:00"
    assert result["aggregate_count"] == len(repository.published[1])
    assert result["recurring_series_count"] == len(repository.published[2])
    assert result["finding_count"] == len(repository.published[3])
    assert result["duration_ms"] == 125
    assert result["affected_periods"] == []


def test_incremental_service_rebuilds_only_affected_period_aggregates() -> None:
    january = _transaction("january", date(2026, 1, 10), "10.00")
    march = _transaction("march", date(2026, 3, 10), "20.00")
    snapshot = AnalyticsSnapshot(
        context=AnalyticsRunContext(
            run_id="incremental-run",
            generation=8,
            mode="incremental",
            sensitivity=Sensitivity.BALANCED,
            source_watermark=datetime(2026, 3, 10, tzinfo=UTC),
        ),
        transactions=(january, march),
        aggregate_transactions=(march,),
        affected_periods=(date(2026, 3, 1),),
        previous_generation=7,
    )
    repository = _MemoryAnalyticsRefreshRepository(snapshot)
    ticks = iter([1.0, 1.01])
    service = AnalyticsRefreshService(
        repository=repository,
        today=lambda: date(2026, 4, 1),
        clock=lambda: next(ticks),
    )

    result = service.run({"mode": "incremental"})

    assert repository.published is not None
    aggregates = repository.published[1]
    assert {aggregate.period_start for aggregate in aggregates} == {date(2026, 3, 1)}
    assert all(aggregate.spending_base == Decimal("20.00") for aggregate in aggregates)
    assert result["affected_periods"] == ["2026-03-01"]


def test_analytics_refresh_service_marks_run_failed_without_publishing() -> None:
    repository = _MemoryAnalyticsRefreshRepository(
        _finding_suite_snapshot(),
        fail_publish=True,
    )
    ticks = iter([10.0, 10.1])
    service = AnalyticsRefreshService(
        repository=repository,
        today=lambda: date(2026, 8, 1),
        clock=lambda: next(ticks),
    )

    with pytest.raises(RuntimeError, match="publication failed"):
        service.run({"mode": "incremental"})

    assert repository.published is None
    assert repository.failed == ("run-1", "publication failed")


def test_analytics_refresh_service_marks_a_requested_run_failed_during_prepare() -> None:
    repository = _MemoryAnalyticsRefreshRepository(
        _finding_suite_snapshot(),
        fail_prepare=True,
    )
    service = AnalyticsRefreshService(repository=repository)

    with pytest.raises(RuntimeError, match="snapshot failed"):
        service.run({"mode": "full", "analytics_run_id": "requested-run"})

    assert repository.published is None
    assert repository.failed == ("requested-run", "snapshot failed")


class _SourceFindingCursor:
    def execute(self, _query: str) -> None:
        pass

    def fetchall(self) -> list[dict[str, object]]:
        return [
            {
                "id": "statement-2",
                "account_id": "account-1",
                "period_start": date(2026, 2, 5),
                "period_end": date(2026, 2, 28),
                "opening_balance": Decimal("100.00"),
                "closing_balance": Decimal("130.00"),
                "currency": "CAD",
                "reconcile_status": "mismatch",
                "transaction_total": Decimal("20.00"),
                "previous_covered_until": date(2026, 1, 31),
            }
        ]


def test_source_findings_include_reconciliation_math_and_exact_gap_interval() -> None:
    findings = PostgresAnalyticsRepository._load_source_findings(  # type: ignore[arg-type]
        _SourceFindingCursor()
    )

    mismatch = next(
        finding
        for finding in findings
        if finding.finding_type is FindingType.RECONCILIATION_MISMATCH
    )
    assert mismatch.evidence["transactionTotal"] == "20.00"
    assert mismatch.evidence["calculatedClosing"] == "120.00"
    assert mismatch.evidence["difference"] == "10.00"
    gap = next(
        finding for finding in findings if finding.finding_type is FindingType.COVERAGE_GAP
    )
    assert gap.evidence["gapStart"] == "2026-02-01"
    assert gap.evidence["gapEnd"] == "2026-02-04"


class _RecordingCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, object]] = []

    def execute(self, query: str, parameters: object = None) -> None:
        self.executed.append((query, parameters))


def test_incremental_publisher_copies_only_unaffected_prior_rows() -> None:
    cursor = _RecordingCursor()

    PostgresAnalyticsRepository._copy_unaffected_aggregates(  # type: ignore[arg-type]
        cursor,
        source_generation=7,
        target_generation=8,
        affected_periods=(date(2026, 3, 1), date(2026, 5, 1)),
    )

    query, parameters = cursor.executed[0]
    assert "SELECT %s" in query
    assert "NOT (period_start = ANY(%s::date[]))" in query
    assert parameters == (8, 7, [date(2026, 3, 1), date(2026, 5, 1)])


def test_occurrence_refresh_preserves_reviewed_series_that_no_longer_match() -> None:
    cursor = _RecordingCursor()

    PostgresAnalyticsRepository._replace_detected_occurrences(  # type: ignore[arg-type]
        cursor,
        generation=8,
        series=(),
        series_ids={},
    )

    assert cursor.executed == []

    rows = [
        _transaction(
            f"current-{index}",
            date(2026, 1, 1) + timedelta(days=30 * index),
            "10.00",
            merchant="current series",
        )
        for index in range(3)
    ]
    current = detect_recurring_series(rows)[0]
    PostgresAnalyticsRepository._replace_detected_occurrences(  # type: ignore[arg-type]
        cursor,
        generation=8,
        series=(current,),
        series_ids={current.detector_fingerprint: "00000000-0000-4000-8000-000000000001"},
    )

    delete_query, delete_parameters = cursor.executed[0]
    assert "series_id = ANY(%s::uuid[])" in delete_query
    assert delete_parameters == (["00000000-0000-4000-8000-000000000001"],)


def test_materially_changed_pending_fx_evidence_gets_a_new_fingerprint() -> None:
    context = AnalyticsRunContext(
        run_id="fingerprint-run",
        generation=1,
        mode="full",
        sensitivity=Sensitivity.BALANCED,
        source_watermark=None,
    )
    original = _transaction(
        "same-transaction",
        date(2026, 1, 1),
        "100.00",
        native_currency="TZS",
        base_amount=None,
    )
    changed = _transaction(
        "same-transaction",
        date(2026, 1, 1),
        "110.00",
        native_currency="TZS",
        base_amount=None,
    )

    first = build_insight_findings(
        AnalyticsSnapshot(context=context, transactions=(original,)),
        recurring_series=(),
        as_of=date(2026, 2, 1),
    )
    second = build_insight_findings(
        AnalyticsSnapshot(context=context, transactions=(changed,)),
        recurring_series=(),
        as_of=date(2026, 2, 1),
    )

    assert first[0].finding_type is FindingType.PENDING_FX
    assert first[0].detector_fingerprint != second[0].detector_fingerprint


def test_detector_parameter_validation() -> None:
    with pytest.raises(ValueError, match="at least two"):
        detect_amount_anomalies([], minimum_prior_observations=1)
    with pytest.raises(ValueError, match="window_days"):
        detect_near_duplicates([], window_days=-1)
    with pytest.raises(ValueError, match="thresholds"):
        detect_price_increases([], percent_threshold=Decimal("-1"))


def test_refresh_materializes_all_and_assigned_market_scopes() -> None:
    snapshot = AnalyticsSnapshot(
        context=AnalyticsRunContext(
            run_id="market-run",
            generation=12,
            mode="full",
            sensitivity=Sensitivity.BALANCED,
            source_watermark=None,
        ),
        transactions=(
            _transaction(
                "ca",
                date(2026, 1, 1),
                "10.00",
                account="ca-account",
                market_code="CA",
            ),
            _transaction(
                "tz",
                date(2026, 1, 2),
                "20.00",
                account="tz-account",
                market_code="TZ",
            ),
            _transaction(
                "unassigned",
                date(2026, 1, 3),
                "30.00",
                account="unassigned-account",
            ),
        ),
    )
    repository = _MemoryAnalyticsRefreshRepository(snapshot)
    ticks = iter([1.0, 1.01])

    AnalyticsRefreshService(
        repository=repository,
        today=lambda: date(2026, 2, 1),
        clock=lambda: next(ticks),
    ).run({"mode": "full"})

    assert repository.published is not None
    ledger_rows = {
        aggregate.market_scope: aggregate
        for aggregate in repository.published[1]
        if aggregate.dimension_type is AggregateDimension.LEDGER
    }
    assert ledger_rows[MarketScope.ALL].spending_base == Decimal("60.00")
    assert ledger_rows[MarketScope.CANADA].spending_base == Decimal("10.00")
    assert ledger_rows[MarketScope.TANZANIA].spending_base == Decimal("20.00")
    assert all(
        aggregate.dimension_key != "unassigned-account"
        for aggregate in repository.published[1]
        if aggregate.market_scope is not MarketScope.ALL
    )


def test_scope_fingerprints_isolate_recurring_review_identity() -> None:
    rows = [
        _transaction(
            f"subscription-{index}",
            date(2026, 1, 1) + timedelta(days=30 * index),
            "10.00",
            merchant="subscription",
            market_code="CA",
        )
        for index in range(3)
    ]

    all_series = detect_recurring_series(rows, market_scope=MarketScope.ALL)[0]
    canada_series = detect_recurring_series(rows, market_scope=MarketScope.CANADA)[0]

    assert all_series.detector_fingerprint != canada_series.detector_fingerprint
    assert all_series.market_scope is MarketScope.ALL
    assert canada_series.market_scope is MarketScope.CANADA


def test_home_currency_policy_only_changes_base_recurring_fingerprints() -> None:
    start = date(2026, 1, 1)
    original_rows = [
        _transaction(
            f"original-policy-{index}",
            start + timedelta(days=30 * index),
            "13000.00",
            native_currency="TZS",
            base_amount="7.00",
            original_amount="5.00",
            original_currency="USD",
            merchant="original policy merchant",
        )
        for index in range(3)
    ]
    native_rows = [
        _transaction(
            f"native-policy-{index}",
            start + timedelta(days=30 * index),
            "5.00",
            native_currency="USD",
            base_amount="7.00",
            merchant="native policy merchant",
        )
        for index in range(3)
    ]
    base_rows = [
        _transaction(
            f"base-policy-{index}",
            start + timedelta(days=30 * index),
            "5.00" if index % 2 == 0 else "13000.00",
            native_currency="USD" if index % 2 == 0 else "TZS",
            base_amount="7.00",
            merchant="base policy merchant",
        )
        for index in range(3)
    ]
    rows = original_rows + native_rows + base_rows

    def detected(base_currency: str, policy: str) -> dict[str, str]:
        return {
            candidate.merchant_key: candidate.detector_fingerprint
            for candidate in detect_recurring_series(
                rows,
                base_currency=base_currency,
                threshold_policy_version=policy,
            )
        }

    cad_v1 = detected("CAD", "materiality-v1")
    tzs_v1 = detected("TZS", "materiality-v1")
    cad_v2 = detected("CAD", "materiality-v2")

    assert cad_v1["base policy merchant"] != tzs_v1["base policy merchant"]
    assert cad_v1["base policy merchant"] != cad_v2["base policy merchant"]
    for merchant in ("original policy merchant", "native policy merchant"):
        assert cad_v1[merchant] == tzs_v1[merchant] == cad_v2[merchant]


def test_home_currency_policy_changes_only_base_sensitive_fingerprints() -> None:
    tzs_thresholds = AnalyticsThresholdProfile(
        base_currency="TZS",
        policy_version="materiality-v1",
        minimum_difference_low=Decimal("46296.30"),
        minimum_difference_balanced=Decimal("18518.52"),
        minimum_difference_high=Decimal("9259.26"),
        minimum_price_increase=Decimal("1851.85"),
    )
    cad_context = AnalyticsRunContext(
        run_id="cad-run",
        generation=1,
        mode="full",
        sensitivity=Sensitivity.BALANCED,
        source_watermark=None,
    )
    tzs_context = AnalyticsRunContext(
        run_id="tzs-run",
        generation=2,
        mode="full",
        sensitivity=Sensitivity.BALANCED,
        source_watermark=None,
        base_currency="TZS",
        threshold_profile=tzs_thresholds,
    )
    pending = _transaction(
        "pending",
        date(2026, 1, 1),
        "10.00",
        native_currency="USD",
        base_amount=None,
    )
    duplicates = (
        _transaction("duplicate-1", date(2026, 1, 2), "10.00"),
        _transaction("duplicate-2", date(2026, 1, 3), "10.00"),
    )

    cad_pending = build_insight_findings(
        AnalyticsSnapshot(context=cad_context, transactions=(pending,)),
        recurring_series=(),
        as_of=date(2026, 2, 1),
    )[0]
    tzs_pending = build_insight_findings(
        AnalyticsSnapshot(context=tzs_context, transactions=(pending,)),
        recurring_series=(),
        as_of=date(2026, 2, 1),
    )[0]
    cad_duplicate = build_insight_findings(
        AnalyticsSnapshot(context=cad_context, transactions=duplicates),
        recurring_series=(),
        as_of=date(2026, 2, 1),
    )[0]
    tzs_duplicate = build_insight_findings(
        AnalyticsSnapshot(context=tzs_context, transactions=duplicates),
        recurring_series=(),
        as_of=date(2026, 2, 1),
    )[0]

    assert cad_pending.detector_fingerprint != tzs_pending.detector_fingerprint
    assert tzs_pending.evidence["baseCurrency"] == "TZS"
    assert tzs_pending.evidence["thresholdPolicyVersion"] == "materiality-v1"
    assert cad_duplicate.finding_type is FindingType.NEAR_DUPLICATE
    assert cad_duplicate.detector_fingerprint == tzs_duplicate.detector_fingerprint
