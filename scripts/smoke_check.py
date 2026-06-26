from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pulseiq.analytics import calculate_kpis, make_insights
from pulseiq.anomaly import detect_anomalies
from pulseiq.assistant import answer_question
from pulseiq.data import load_demo_data
from pulseiq.model import score_customer, train_models
from pulseiq.report import build_report_pdf


def main() -> None:
    df = load_demo_data()
    assert len(df) >= 1000, "demo dataset should be portfolio-sized"

    anomalies = detect_anomalies(df)
    kpis = calculate_kpis(df, anomalies)
    assert kpis["records_processed"] == len(df)
    assert kpis["suspicious_transactions"] > 0

    bundle = train_models(df)
    assert bundle.metrics["f1_score"] >= 0

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
    assert "decision" in result

    insights = make_insights(df, kpis, anomalies, bundle.metrics)
    pdf = build_report_pdf(df, kpis, anomalies, insights, bundle.name, bundle.metrics)
    assert len(pdf) > 3000

    reply = answer_question("What is the biggest risk?", df, kpis, anomalies, bundle.metrics)
    assert reply

    print("PulseIQ smoke check passed")
    print(f"Rows: {len(df):,}")
    print(f"Model: {bundle.name}")
    print(f"Metrics: {bundle.metrics}")
    print(f"Suspicious records: {kpis['suspicious_transactions']:,}")


if __name__ == "__main__":
    main()
