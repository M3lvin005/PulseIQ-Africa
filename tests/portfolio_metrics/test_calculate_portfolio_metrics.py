"""Acceptance tests for governed portfolio metrics."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from pulseiq.portfolio_metrics import MetricId, MetricQualityStatus, MetricStatus, calculate_portfolio_metrics


def _complete_frame() -> pd.DataFrame:
    """Return one row that satisfies every current prototype capability."""

    return pd.DataFrame(
        {
            "customer_id": ["CUST-1"],
            "date": ["2026-01-01"],
            "transaction_amount": [1200],
            "defaulted": [0],
            "income": [100_000],
            "loan_amount": [50_000],
            "repayment_history_score": [80],
            "existing_debt": [10_000],
            "transaction_frequency": [12],
            "account_age_months": [24],
            "employment_status": ["Salaried"],
            "segment": ["Retail"],
            "business_type": ["Shop"],
            "region": ["Lagos"],
        }
    )


def test_missing_transaction_amount_is_unavailable_not_zero() -> None:
    """REQ-KPI-002: a missing dependency returns Not available, never zero."""

    snapshot = calculate_portfolio_metrics(
        pd.DataFrame({"customer_id": ["CUST-1"], "date": ["2026-01-01"]}),
        currency="NGN",
    )

    metric = snapshot.metric(MetricId.TRANSACTION_VALUE)
    assert metric.status is MetricStatus.UNAVAILABLE
    assert metric.value is None
    assert metric.unavailable_reason
    assert metric.recovery


def test_financial_metric_requires_confirmed_currency() -> None:
    """REQ-KPI-001/003: a financial aggregate carries explicit currency semantics."""

    snapshot = calculate_portfolio_metrics(
        pd.DataFrame({"transaction_amount": [1200], "date": ["2026-01-01"]}),
    )

    metric = snapshot.metric(MetricId.TRANSACTION_VALUE)
    assert metric.status is MetricStatus.UNAVAILABLE
    assert metric.value is None
    assert "currency" in str(metric.unavailable_reason).lower()


def test_unparseable_amounts_do_not_sum_to_zero() -> None:
    """Invalid critical values inherit the dataset capability block."""

    snapshot = calculate_portfolio_metrics(
        pd.DataFrame(
            {
                "transaction_amount": ["unknown", "invalid"],
                "date": ["2026-01-01", "2026-01-02"],
            }
        ),
        currency="NGN",
    )

    metric = snapshot.metric(MetricId.TRANSACTION_VALUE)
    assert metric.status is MetricStatus.UNAVAILABLE
    assert metric.value is None
    assert "parseable" in str(metric.unavailable_reason).lower()


def test_available_transaction_value_carries_full_provenance() -> None:
    """REQ-KPI-001: every available KPI explains its meaning and source."""

    generated_at = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    snapshot = calculate_portfolio_metrics(
        pd.DataFrame(
            {
                "transaction_amount": [1200, 800],
                "date": ["2026-01-01", "2026-01-31"],
            }
        ),
        currency="ngn",
        generated_at=generated_at,
    )

    metric = snapshot.metric(MetricId.TRANSACTION_VALUE)
    assert metric.status is MetricStatus.AVAILABLE
    assert metric.value == 2000.0
    assert metric.label == "Total transaction value"
    assert metric.currency == "NGN"
    assert metric.unit == "currency"
    assert metric.period is not None
    assert metric.period.start.isoformat() == "2026-01-01"
    assert metric.period.end.isoformat() == "2026-01-31"
    assert metric.definition_version == "portfolio.transaction-value/1.0.0"
    assert metric.quality_status is MetricQualityStatus.HEALTHY
    assert metric.source_reference == snapshot.dataset_reference
    assert metric.source_reference.startswith("dataframe:sha256:")
    assert snapshot.generated_at == generated_at


def test_missing_customer_identifier_makes_unique_customers_unavailable() -> None:
    """Customer counts require an explicit identifier instead of row count fallback."""

    snapshot = calculate_portfolio_metrics(
        pd.DataFrame({"transaction_amount": [1200], "date": ["2026-01-01"]}),
        currency="NGN",
    )

    metric = snapshot.metric(MetricId.UNIQUE_CUSTOMERS)
    assert metric.status is MetricStatus.UNAVAILABLE
    assert metric.value is None
    assert "customer" in str(metric.unavailable_reason).lower()


def test_empty_dataset_observations_are_zero_but_dependent_metrics_are_unavailable() -> None:
    """A real zero record count is distinct from a fabricated zero business KPI."""

    snapshot = calculate_portfolio_metrics(pd.DataFrame())

    assert snapshot.metric(MetricId.RECORDS_PROCESSED).value == 0
    assert snapshot.metric(MetricId.DATA_QUALITY_SCORE).value == 0.0
    assert snapshot.metric(MetricId.MISSING_VALUES).value == 0
    assert snapshot.metric(MetricId.DUPLICATE_ROWS).value == 0
    assert snapshot.metric(MetricId.TRANSACTION_VALUE).status is MetricStatus.UNAVAILABLE


def test_average_transaction_value_uses_only_parseable_values() -> None:
    """The average shares transaction dependencies and never median-imputes rows."""

    snapshot = calculate_portfolio_metrics(
        pd.DataFrame(
            {
                "transaction_amount": [1200, "invalid", 800],
                "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
            }
        ),
        currency="NGN",
    )

    metric = snapshot.metric(MetricId.AVERAGE_TRANSACTION_VALUE)
    assert metric.status is MetricStatus.AVAILABLE
    assert metric.value == 1000.0
    assert metric.currency == "NGN"
    assert metric.quality_status is MetricQualityStatus.WARN


def test_non_default_outcome_share_is_not_labelled_repayment_rate() -> None:
    """REQ-KPI-006: a row outcome share must not claim scheduled repayment."""

    snapshot = calculate_portfolio_metrics(
        pd.DataFrame(
            {
                "defaulted": [0, 1, 0, 1],
                "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
            }
        )
    )

    metric = snapshot.metric(MetricId.NON_DEFAULT_OUTCOME_SHARE)
    assert metric.status is MetricStatus.AVAILABLE
    assert metric.label == "Non-default outcome share"
    assert "repayment" not in metric.label.lower()
    assert metric.value == 50.0
    assert metric.numerator == 2
    assert metric.denominator == 4


def test_risk_counts_are_unavailable_without_a_versioned_rule_run() -> None:
    """Risk terminology cannot fall back to stored demo labels."""

    snapshot = calculate_portfolio_metrics(
        pd.DataFrame(
            {
                "transaction_amount": [1200],
                "date": ["2026-01-01"],
            }
        ),
        currency="NGN",
    )

    assert snapshot.metric(MetricId.SUSPICIOUS_RECORDS).status is MetricStatus.UNAVAILABLE
    assert snapshot.metric(MetricId.HIGH_RISK_RECORDS).status is MetricStatus.UNAVAILABLE


def test_risk_counts_carry_the_exact_rule_version() -> None:
    """REQ-RISK-001/KPI-001: rule-derived counts retain rule provenance."""

    dataframe = pd.DataFrame(
        {
            "transaction_amount": [1200, 800],
            "date": ["2026-01-01", "2026-01-02"],
            "income": [100_000, 80_000],
            "loan_amount": [50_000, 120_000],
            "existing_debt": [10_000, 30_000],
            "repayment_history_score": [80, 40],
            "transaction_frequency": [12, 30],
        }
    )
    rule_results = pd.DataFrame(
        {
            "is_suspicious": [False, True],
            "risk_level": ["Normal", "High"],
        }
    )

    snapshot = calculate_portfolio_metrics(
        dataframe,
        currency="NGN",
        anomaly_dataframe=rule_results,
        risk_rule_version="prototype-risk-rules/1.0.0",
    )

    suspicious = snapshot.metric(MetricId.SUSPICIOUS_RECORDS)
    high_priority = snapshot.metric(MetricId.HIGH_RISK_RECORDS)
    assert suspicious.value == 1
    assert high_priority.value == 1
    assert suspicious.logic_version == "prototype-risk-rules/1.0.0"
    assert high_priority.logic_version == "prototype-risk-rules/1.0.0"


def test_single_currency_column_is_normalized_and_mixed_currency_is_blocked() -> None:
    """Currency can be sourced from one unambiguous mapped column."""

    single_currency = pd.DataFrame(
        {
            "transaction_amount": [1200, 800],
            "date": ["2026-01-01", "2026-01-02"],
            "currency": ["ghs", " GHS "],
        }
    )
    mixed_currency = single_currency.assign(currency=["GHS", "NGN"])

    available = calculate_portfolio_metrics(single_currency).metric(MetricId.TRANSACTION_VALUE)
    unavailable = calculate_portfolio_metrics(mixed_currency).metric(MetricId.TRANSACTION_VALUE)

    assert available.currency == "GHS"
    assert available.status is MetricStatus.AVAILABLE
    assert unavailable.status is MetricStatus.UNAVAILABLE


def test_invalid_and_partial_default_outcomes_have_explicit_states() -> None:
    """Outcome denominators contain only approved binary values."""

    invalid = calculate_portfolio_metrics(pd.DataFrame({"defaulted": ["bad"], "date": ["invalid"]}))
    partial = calculate_portfolio_metrics(pd.DataFrame({"defaulted": [0, 1, "bad"]}))

    unavailable = invalid.metric(MetricId.NON_DEFAULT_OUTCOME_SHARE)
    warned = partial.metric(MetricId.NON_DEFAULT_OUTCOME_SHARE)
    assert unavailable.status is MetricStatus.UNAVAILABLE
    assert unavailable.period is None
    assert warned.status is MetricStatus.AVAILABLE
    assert warned.quality_status is MetricQualityStatus.WARN
    assert warned.denominator == 2


def test_rule_metrics_block_invalid_source_and_missing_rule_inputs() -> None:
    """Both source schema and source-data fitness are enforced for rule counts."""

    incomplete_output = calculate_portfolio_metrics(
        _complete_frame(),
        currency="NGN",
        anomaly_dataframe=pd.DataFrame({"is_suspicious": [True]}),
        risk_rule_version="prototype-risk-rules/1.0.0",
    )
    incomplete_source = calculate_portfolio_metrics(
        pd.DataFrame({"transaction_amount": [1200], "date": ["2026-01-01"]}),
        currency="NGN",
        anomaly_dataframe=pd.DataFrame({"is_suspicious": [True], "risk_level": ["High"]}),
        risk_rule_version="prototype-risk-rules/1.0.0",
    )

    assert incomplete_output.metric(MetricId.SUSPICIOUS_RECORDS).status is MetricStatus.UNAVAILABLE
    source_metric = incomplete_source.metric(MetricId.SUSPICIOUS_RECORDS)
    assert source_metric.status is MetricStatus.UNAVAILABLE
    assert "missing required inputs" in str(source_metric.unavailable_reason).lower()


def test_dataset_observation_quality_warns_without_hiding_available_capabilities() -> None:
    """A non-blocking issue is preserved on the observable quality metric."""

    dataframe = _complete_frame()
    dataframe.loc[0, "employment_status"] = None

    metric = calculate_portfolio_metrics(dataframe, currency="NGN").metric(MetricId.DATA_QUALITY_SCORE)

    assert metric.status is MetricStatus.AVAILABLE
    assert metric.quality_status is MetricQualityStatus.WARN
