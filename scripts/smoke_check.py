from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pulseiq.anomaly import RULESET_VERSION, detect_anomalies
from pulseiq.assistant import answer_question
from pulseiq.data import load_demo_data
from pulseiq.model import score_customer, train_models
from pulseiq.portfolio_metrics import MetricId, build_metric_insights, calculate_portfolio_metrics
from pulseiq.report import build_report_pdf


def require(condition: bool, message: str) -> None:
    """Raise a durable smoke-check failure even when optimization is enabled."""
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    df = load_demo_data()
    require(len(df) >= 1000, "Demo dataset should be portfolio-sized.")

    anomalies = detect_anomalies(df)
    metrics = calculate_portfolio_metrics(
        df,
        currency="NGN",
        anomaly_dataframe=anomalies,
        risk_rule_version=RULESET_VERSION,
    )
    require(metrics.metric(MetricId.RECORDS_PROCESSED).value == len(df), "Processed-row metric is inconsistent.")
    require(int(metrics.metric(MetricId.SUSPICIOUS_RECORDS).value or 0) > 0, "Demo rule run found no records.")

    bundle = train_models(df)
    require(bundle.metrics["f1_score"] >= 0, "Model F1 score is invalid.")

    result = score_customer(
        bundle,
        {
            "income": 220000,
            "loan_amount": 180000,
            "repayment_history_score": 72,
            "existing_debt": 35000,
            "transaction_frequency": 24,
            "account_age_months": 28,
            "employment_status": "Salaried",
            "segment": "Retail",
            "business_type": "Shop",
            "region": "Lagos",
        },
    )
    require(result["routing"] == "Manual review required", "Model output bypassed manual review.")

    insights = list(build_metric_insights(metrics))
    pdf = build_report_pdf(
        df,
        metrics,
        anomalies,
        insights,
        bundle.name,
        bundle.metrics,
        bundle.provenance.run_id,
        bundle.provenance.split_strategy,
        bundle.provenance.probability_status,
    )
    require(len(pdf) > 3000, "Generated PDF is unexpectedly small.")

    reply = answer_question("What is the biggest risk?", df, metrics, anomalies, bundle.metrics)
    require(bool(reply), "Assistant returned an empty response.")

    print("PulseIQ smoke check passed")
    print(f"Rows: {len(df):,}")
    print(f"Model: {bundle.name}")
    print(f"Metrics: {bundle.metrics}")
    print(f"Suspicious records: {int(metrics.metric(MetricId.SUSPICIOUS_RECORDS).value or 0):,}")


if __name__ == "__main__":
    main()
