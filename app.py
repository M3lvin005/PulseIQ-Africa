from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pulseiq.analytics import (  # noqa: E402
    calculate_kpis,
    categorical_counts,
    default_breakdown,
    make_insights,
    monthly_revenue,
)
from pulseiq.anomaly import anomaly_summary, detect_anomalies  # noqa: E402
from pulseiq.assistant import answer_question  # noqa: E402
from pulseiq.data import data_quality, load_csv, load_demo_data  # noqa: E402
from pulseiq.model import ModelBundle, score_customer, train_models  # noqa: E402
from pulseiq.report import build_report_pdf  # noqa: E402
from pulseiq.ui import apply_page_style, currency_metric, hero, require_dataset_message, value_card  # noqa: E402


st.set_page_config(
    page_title="PulseIQ Africa",
    page_icon="PIQ",
    layout="wide",
    initial_sidebar_state="expanded",
)


def init_state() -> None:
    st.session_state.setdefault("data", None)
    st.session_state.setdefault("data_source", "No dataset loaded")
    st.session_state.setdefault("model_bundle", None)


def set_demo_data() -> None:
    st.session_state.data = load_demo_data()
    st.session_state.data_source = "Built-in demo loan and transaction data"
    st.session_state.model_bundle = None


def get_data() -> pd.DataFrame | None:
    data = st.session_state.get("data")
    if data is None:
        return None
    return data.copy()


def sidebar_nav() -> str:
    st.sidebar.title("PulseIQ Africa")
    st.sidebar.caption("Decision intelligence for small businesses and financial teams.")
    page = st.sidebar.radio(
        "Workspace",
        [
            "Home",
            "Upload Data",
            "Dashboard",
            "Prediction",
            "Anomaly Detection",
            "Report",
            "Insight Assistant",
            "About Project",
        ],
    )
    st.sidebar.divider()
    if st.sidebar.button("Load demo dataset", use_container_width=True):
        set_demo_data()
        st.sidebar.success("Demo dataset loaded.")
    st.sidebar.caption(st.session_state.get("data_source", "No dataset loaded"))
    return page


def page_home() -> None:
    hero(
        "PulseIQ Africa",
        "Turning raw business records into clean dashboards, risk predictions, suspicious-activity checks, and automated decision reports.",
    )
    c1, c2 = st.columns([1.1, 0.9])
    with c1:
        st.subheader("Decision flow")
        st.write(
            "Data comes in, PulseIQ cleans it, reveals patterns, scores risk, flags suspicious records, and produces a report that a reviewer can act on."
        )
        a, b = st.columns(2)
        if a.button("Try demo dataset", type="primary", use_container_width=True):
            set_demo_data()
            st.success("Demo dataset loaded. Open the Dashboard page to explore it.")
        if b.button("Go to upload page", use_container_width=True):
            st.session_state["_nav_hint"] = "Upload Data"
            st.info("Use the sidebar to open Upload Data.")
    with c2:
        st.subheader("Portfolio proof")
        data = get_data()
        if data is not None:
            anomalies = detect_anomalies(data)
            kpis = calculate_kpis(data, anomalies)
            st.metric("Records processed", f"{kpis['records_processed']:,}")
            st.metric("Data quality score", f"{kpis['data_quality_score']:.1f}%")
            st.metric("Suspicious records", f"{kpis['suspicious_transactions']:,}")
        else:
            st.info("Load the demo dataset to preview live measurements.")

    st.divider()
    v1, v2, v3 = st.columns(3)
    with v1:
        value_card("Analyze", "Turn spreadsheet records into KPIs, trends, charts, and customer segment insight.")
    with v2:
        value_card("Predict", "Train measurable risk models and score new customer or loan applications.")
    with v3:
        value_card("Protect", "Flag abnormal amounts, duplicate records, repayment pressure, and profile mismatches.")


def page_upload() -> None:
    st.title("Upload Data")
    st.caption("CSV files are normalized into a shared schema where possible.")

    uploaded = st.file_uploader("Upload CSV", type=["csv"])
    c1, c2 = st.columns([0.55, 0.45])
    with c1:
        if uploaded is not None:
            try:
                st.session_state.data = load_csv(uploaded)
                st.session_state.data_source = uploaded.name
                st.session_state.model_bundle = None
                st.success(f"Loaded {uploaded.name}.")
            except Exception as exc:  # pragma: no cover - Streamlit feedback path
                st.error(f"Could not read this CSV: {exc}")
        if st.button("Use sample business data", type="primary"):
            set_demo_data()
            st.success("Demo dataset loaded.")
    with c2:
        st.write("Expected fields include income, loan amount, transaction amount, repayment history, and customer or transaction IDs.")

    data = get_data()
    if data is None:
        require_dataset_message()
        return

    quality = data_quality(data)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Rows", f"{quality.rows:,}")
    m2.metric("Columns", f"{quality.columns:,}")
    m3.metric("Missing values", f"{quality.missing_values:,}")
    m4.metric("Duplicate rows", f"{quality.duplicate_rows:,}")
    m5.metric("Quality score", f"{quality.score:.1f}%")
    st.subheader("Data preview")
    st.dataframe(data.head(50), use_container_width=True, height=360)


def page_dashboard() -> None:
    st.title("Dashboard")
    data = get_data()
    if data is None:
        require_dataset_message()
        return

    anomalies = detect_anomalies(data)
    kpis = calculate_kpis(data, anomalies)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total revenue", currency_metric(kpis["total_revenue"]))
    m2.metric("Total customers", f"{kpis['total_customers']:,}")
    m3.metric("Avg. transaction", currency_metric(kpis["average_transaction_value"]))
    m4.metric("Repayment rate", f"{kpis['loan_repayment_rate']:.1f}%")

    m5, m6, m7, m8 = st.columns(4)
    m5.metric("Records processed", f"{kpis['records_processed']:,}")
    m6.metric("High-risk customers", f"{kpis['high_risk_customers']:,}")
    m7.metric("Suspicious records", f"{kpis['suspicious_transactions']:,}")
    m8.metric("Data quality", f"{kpis['data_quality_score']:.1f}%")

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        revenue = monthly_revenue(data)
        fig = px.line(revenue, x="month", y="transaction_amount", markers=True, title="Monthly revenue trend")
        fig.update_layout(yaxis_title="Transaction value", xaxis_title="Month")
        st.plotly_chart(fig, use_container_width=True)

        breakdown = default_breakdown(data)
        fig = px.bar(breakdown, x="repayment_status", y="records", title="Loan repayment vs default")
        fig.update_layout(xaxis_title="Status", yaxis_title="Records")
        st.plotly_chart(fig, use_container_width=True)

        if "segment" in data.columns:
            segments = categorical_counts(data, "segment").head(8)
            fig = px.bar(segments, x="segment", y="records", title="Top customer segments")
            fig.update_layout(xaxis_title="Segment", yaxis_title="Records")
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        if "risk_level" in anomalies.columns:
            risk = categorical_counts(anomalies, "risk_level")
            fig = px.pie(risk, names="risk_level", values="records", title="Customer risk level")
            st.plotly_chart(fig, use_container_width=True)

        if "transaction_amount" in data.columns:
            fig = px.histogram(data, x="transaction_amount", nbins=38, title="Transaction amount distribution")
            fig.update_layout(xaxis_title="Transaction value", yaxis_title="Records")
            st.plotly_chart(fig, use_container_width=True)

        summary = anomaly_summary(anomalies)
        if not summary.empty:
            category = summary.groupby("suspicious_category")["records"].sum().reset_index().sort_values("records")
            fig = px.bar(category, x="records", y="suspicious_category", orientation="h", title="Suspicious activity by category")
            fig.update_layout(xaxis_title="Records", yaxis_title="Issue")
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Insight snapshot")
    for insight in make_insights(data, kpis, anomalies):
        st.write(f"- {insight}")


def page_prediction() -> None:
    st.title("Prediction")
    data = get_data()
    if data is None:
        require_dataset_message()
        return

    if st.button("Train prediction models", type="primary"):
        with st.spinner("Training Logistic Regression, Random Forest, and Decision Tree models..."):
            st.session_state.model_bundle = train_models(data)

    bundle: ModelBundle | None = st.session_state.get("model_bundle")
    if bundle is None:
        st.info("Train the models to view evaluation metrics and score a customer.")
        return

    st.subheader(f"Selected model: {bundle.name}")
    leaderboard = pd.DataFrame(bundle.leaderboard)
    st.dataframe(leaderboard, use_container_width=True, hide_index=True)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Accuracy", f"{bundle.metrics['accuracy']:.2f}")
    m2.metric("Precision", f"{bundle.metrics['precision']:.2f}")
    m3.metric("Recall", f"{bundle.metrics['recall']:.2f}")
    m4.metric("F1-score", f"{bundle.metrics['f1_score']:.2f}")
    m5.metric("ROC-AUC", f"{bundle.metrics['roc_auc']:.2f}")

    st.subheader("Confusion matrix")
    matrix = pd.DataFrame(
        bundle.confusion_matrix,
        index=["Actual repaid", "Actual defaulted"],
        columns=["Predicted repaid", "Predicted defaulted"],
    )
    st.dataframe(matrix, use_container_width=True)

    st.subheader("Score a customer")
    with st.form("score_customer_form"):
        c1, c2, c3 = st.columns(3)
        values = {
            "income": c1.number_input("Monthly income", min_value=0.0, value=220000.0, step=10000.0),
            "loan_amount": c2.number_input("Loan amount", min_value=0.0, value=180000.0, step=10000.0),
            "repayment_history_score": c3.slider("Repayment history score", 0, 100, 72),
            "existing_debt": c1.number_input("Existing debt", min_value=0.0, value=35000.0, step=5000.0),
            "transaction_frequency": c2.number_input("Monthly transaction frequency", min_value=0.0, value=24.0, step=1.0),
            "account_age_months": c3.number_input("Account age in months", min_value=0, value=28, step=1),
            "employment_status": c1.selectbox("Employment status", ["Salaried", "Self-employed", "Contract", "Informal", "Unemployed"]),
            "segment": c2.selectbox("Segment", ["Retail", "Market Trader", "SME", "Agriculture", "Services"]),
            "business_type": c3.selectbox("Business type", ["Shop", "Transport", "Food", "Education", "Health", "Fintech Agent"]),
            "region": c1.selectbox("Region", ["Lagos", "Abuja", "Kano", "Accra", "Kumasi", "Nairobi", "Kigali"]),
        }
        submitted = st.form_submit_button("Predict default risk")

    if submitted:
        result = score_customer(bundle, values)
        r1, r2, r3 = st.columns(3)
        r1.metric("Risk score", f"{result['risk_score']:.1f}%")
        r2.metric("Decision", result["decision"])
        r3.metric("Reason", result["reason"])
        st.success(result["suggested_action"])


def page_anomaly() -> None:
    st.title("Anomaly Detection")
    data = get_data()
    if data is None:
        require_dataset_message()
        return

    anomalies = detect_anomalies(data)
    summary = anomaly_summary(anomalies)
    flagged = anomalies[anomalies["is_suspicious"]].sort_values("anomaly_score", ascending=False)

    c1, c2, c3 = st.columns(3)
    c1.metric("Flagged records", f"{len(flagged):,}")
    c2.metric("High-risk flags", f"{int((flagged['risk_level'] == 'High').sum()):,}")
    c3.metric("Top anomaly score", f"{flagged['anomaly_score'].max() if not flagged.empty else 0:.1f}")

    if not summary.empty:
        fig = px.bar(summary, x="records", y="suspicious_category", color="risk_level", orientation="h", title="Suspicious records by rule")
        fig.update_layout(xaxis_title="Records", yaxis_title="Rule")
        st.plotly_chart(fig, use_container_width=True)

    display_cols = [
        column
        for column in [
            "transaction_id",
            "customer_id",
            "date",
            "transaction_amount",
            "loan_amount",
            "income",
            "suspicious_category",
            "risk_level",
            "anomaly_score",
            "anomaly_notes",
        ]
        if column in flagged.columns
    ]
    st.subheader("Flagged record review")
    st.dataframe(flagged[display_cols].head(250), use_container_width=True, height=430)
    st.download_button(
        "Download flagged records CSV",
        data=flagged.to_csv(index=False).encode("utf-8"),
        file_name="pulseiq_flagged_records.csv",
        mime="text/csv",
    )


def page_report() -> None:
    st.title("Automated Report")
    data = get_data()
    if data is None:
        require_dataset_message()
        return

    anomalies = detect_anomalies(data)
    kpis = calculate_kpis(data, anomalies)
    bundle: ModelBundle | None = st.session_state.get("model_bundle")
    insights = make_insights(data, kpis, anomalies, bundle.metrics if bundle else None)

    st.subheader("Report preview")
    for insight in insights:
        st.write(f"- {insight}")

    start = time.perf_counter()
    pdf = build_report_pdf(
        data,
        kpis,
        anomalies,
        insights,
        model_name=bundle.name if bundle else None,
        model_metrics=bundle.metrics if bundle else None,
    )
    elapsed = time.perf_counter() - start
    st.metric("Report generation time", f"{elapsed:.2f}s")
    st.download_button(
        "Download PulseIQ report PDF",
        data=pdf,
        file_name="pulseiq_business_intelligence_report.pdf",
        mime="application/pdf",
        type="primary",
    )


def page_assistant() -> None:
    st.title("Insight Assistant")
    data = get_data()
    if data is None:
        require_dataset_message()
        return

    anomalies = detect_anomalies(data)
    kpis = calculate_kpis(data, anomalies)
    bundle: ModelBundle | None = st.session_state.get("model_bundle")

    quick = st.selectbox(
        "Question",
        [
            "What is the biggest risk?",
            "What should the business do next?",
            "Why was this transaction flagged?",
            "How good is the data quality?",
            "How did the model perform?",
            "What is the revenue picture?",
        ],
    )
    custom = st.text_input("Ask your own question")
    question = custom or quick
    st.write(answer_question(question, data, kpis, anomalies, bundle.metrics if bundle else None))


def page_about() -> None:
    st.title("About Project")
    st.write(
        "PulseIQ Africa is an AI-powered decision intelligence web app for small businesses and financial teams. It turns raw spreadsheet data into useful insights by combining data analysis, machine learning, anomaly detection, automation, and product design."
    )
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Tech stack")
        st.write("- Streamlit")
        st.write("- Python")
        st.write("- pandas and numpy")
        st.write("- Plotly")
        st.write("- scikit-learn")
        st.write("- ReportLab")
    with c2:
        st.subheader("Future improvements")
        st.write("- User login")
        st.write("- Real database")
        st.write("- Admin dashboard")
        st.write("- AI chatbot API")
        st.write("- Email report delivery")
        st.write("- Role-based access")


def main() -> None:
    init_state()
    apply_page_style()
    page = sidebar_nav()
    pages = {
        "Home": page_home,
        "Upload Data": page_upload,
        "Dashboard": page_dashboard,
        "Prediction": page_prediction,
        "Anomaly Detection": page_anomaly,
        "Report": page_report,
        "Insight Assistant": page_assistant,
        "About Project": page_about,
    }
    pages[page]()


if __name__ == "__main__":
    main()
