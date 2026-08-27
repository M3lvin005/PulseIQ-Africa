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

from pulseiq.analytics import (
    categorical_counts,
    default_breakdown,
    monthly_revenue,
)
from pulseiq.anomaly import RULESET_VERSION, anomaly_summary, detect_anomalies, rule_coverage
from pulseiq.assistant import answer_question
from pulseiq.data import load_demo_data
from pulseiq.datasets import DatasetCapability, IssueSeverity, assess_dataset
from pulseiq.exports import safe_csv_bytes
from pulseiq.ingestion import (
    DEFAULT_UPLOAD_POLICY,
    UploadRejected,
    ingest_csv,
    suggest_semantic_mappings,
)
from pulseiq.model import ModelBundle, ModelEligibilityError, assess_model_eligibility, score_customer, train_models
from pulseiq.modeling import EligibilityStatus
from pulseiq.portfolio_metrics import (
    MetricId,
    MetricStatus,
    build_metric_insights,
    calculate_portfolio_metrics,
)
from pulseiq.report import build_report_html, build_report_pdf
from pulseiq.ui import (
    THEME_MODES,
    apply_page_style,
    hero,
    mobile_navigation,
    render_chart_data_table,
    render_dataset_assessment,
    render_governed_metric,
    render_semantic_table,
    render_theme_switcher,
    render_trust_ribbon,
    render_workflow_steps,
    require_dataset_capability,
    require_dataset_message,
    sidebar_brand,
    value_card,
)

st.set_page_config(
    page_title="PulseIQ Africa",
    page_icon="PIQ",
    layout="wide",
    initial_sidebar_state="auto",
)

px.defaults.template = "plotly_white"
px.defaults.color_discrete_sequence = ["#3154F5", "#35BFEA", "#0B1739", "#087A5B", "#E7B957", "#D66B63"]

NAV_OPTIONS = (
    "Home",
    "Upload Data",
    "Dashboard",
    "Prediction",
    "Anomaly Detection",
    "Report",
    "Insight Assistant",
    "About Project",
)
NAV_LABELS = {
    "Home": "Overview",
    "Upload Data": "Data workspace",
    "Dashboard": "Portfolio",
    "Prediction": "Model exploration",
    "Anomaly Detection": "Risk review",
    "Report": "Reports",
    "Insight Assistant": "Assistant",
    "About Project": "About",
}


def init_state() -> None:
    st.session_state.setdefault("data", None)
    st.session_state.setdefault("data_source", "No dataset loaded")
    st.session_state.setdefault("data_currency", None)
    st.session_state.setdefault("dataset_currency_choice", st.session_state.data_currency or "Not confirmed")
    st.session_state.setdefault("ingestion_metadata", None)
    st.session_state.setdefault("header_mappings", ())
    st.session_state.setdefault("model_bundle", None)
    st.session_state.setdefault("workspace_page", "Home")
    st.session_state.setdefault("theme_mode", "System")


def set_demo_data() -> None:
    st.session_state.data = load_demo_data()
    st.session_state.data_source = "Built-in demo loan and transaction data"
    st.session_state.data_currency = "NGN"
    st.session_state.dataset_currency_choice = "NGN"
    st.session_state.ingestion_metadata = None
    st.session_state.header_mappings = ()
    st.session_state.model_bundle = None


def get_data() -> pd.DataFrame | None:
    data = st.session_state.get("data")
    if data is None:
        return None
    return data.copy()


def navigate_to(page: str) -> None:
    """Change the keyed workspace selection during a widget callback."""

    st.session_state.workspace_page = page


def navigate_from_mobile() -> None:
    """Synchronize the phone navigation control with the shared page state."""

    page = st.session_state.get("mobile_workspace_page")
    if page in NAV_OPTIONS:
        st.session_state.workspace_page = page
        st.session_state.mobile_navigation_for = page


def sidebar_nav() -> str:
    st.sidebar.markdown('<a class="skip-link" href="#main-content">Skip to main content</a>', unsafe_allow_html=True)
    sidebar_brand()
    page = st.sidebar.radio(
        "Workspace",
        NAV_OPTIONS,
        format_func=NAV_LABELS.__getitem__,
        key="workspace_page",
    )
    st.sidebar.divider()
    st.sidebar.caption("ACTIVE DATASET")
    if st.sidebar.button("Load demo dataset", width="stretch", on_click=set_demo_data):
        st.sidebar.success("Demo dataset loaded.")
    st.sidebar.caption(st.session_state.get("data_source", "No dataset loaded"))
    return page


def page_home() -> None:
    hero(
        "Know what is trustworthy. Act on what needs attention.",
        "A governed portfolio workspace for analysts, risk reviewers, and data stewards—built around evidence, "
        "not black-box conclusions.",
    )
    data = get_data()
    assessment = assess_dataset(data) if data is not None else None
    render_trust_ribbon(
        assessment,
        source=st.session_state.get("data_source", "No dataset loaded"),
        mapping_review_required=bool(st.session_state.get("header_mappings")),
    )

    if data is None or assessment is None:
        c1, c2 = st.columns([1.15, 0.85])
        with c1:
            st.header("Start with traceable evidence")
            st.write(
                "Upload a bounded CSV and review its meaning and quality before PulseIQ enables portfolio, "
                "risk, model, or report workflows."
            )
            a, b = st.columns(2)
            if a.button("Try demo dataset", type="primary", width="stretch"):
                set_demo_data()
                st.rerun()
            b.button("Go to upload page", width="stretch", on_click=navigate_to, args=("Upload Data",))
        with c2:
            st.header("What happens next")
            value_card("1 · Establish meaning", "Confirm source fields, concepts, units, period, and currency.")
            value_card(
                "2 · Prove fitness",
                "See blocking issues, warnings, recovery actions, and exact quality evidence.",
            )
        return

    anomalies = detect_anomalies(data) if assessment.can(DatasetCapability.RISK_RULE_EVALUATION) else None
    metrics = calculate_portfolio_metrics(
        data,
        currency=st.session_state.get("data_currency"),
        anomaly_dataframe=anomalies,
        risk_rule_version=RULESET_VERSION if anomalies is not None else None,
    )

    st.header("Decision overview")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        render_governed_metric(metrics.metric(MetricId.RECORDS_PROCESSED))
    with m2:
        render_governed_metric(metrics.metric(MetricId.DATA_QUALITY_SCORE))
    with m3:
        render_governed_metric(metrics.metric(MetricId.HIGH_RISK_RECORDS))
    with m4:
        render_governed_metric(metrics.metric(MetricId.SUSPICIOUS_RECORDS))

    evidence, attention = st.columns([1.55, 0.75])
    with evidence:
        st.header("Portfolio evidence")
        transaction_metric = metrics.metric(MetricId.TRANSACTION_VALUE)
        if transaction_metric.status is MetricStatus.AVAILABLE:
            transaction_trend = monthly_revenue(data)
            fig = px.line(
                transaction_trend,
                x="month",
                y="transaction_amount",
                markers=True,
                title="Monthly transaction value",
            )
            fig.update_traces(line_width=3, marker_size=7)
            fig.update_layout(
                yaxis_title=f"Transaction value ({transaction_metric.currency})",
                xaxis_title="Month",
                margin=dict(l=24, r=24, t=64, b=24),
            )
            st.plotly_chart(fig, width="stretch")
            render_chart_data_table("Monthly transaction value", transaction_trend)
        else:
            st.info("Transaction evidence becomes available after amount, currency, and period are confirmed.")

    with attention:
        st.header("Attention queue")
        warning_count = sum(issue.severity is IssueSeverity.WARN for issue in assessment.issues)
        blocking_count = sum(issue.severity is IssueSeverity.BLOCK for issue in assessment.issues)
        flagged_count = len(anomalies.loc[anomalies["is_suspicious"]]) if anomalies is not None else 0
        if blocking_count:
            st.error(f"{blocking_count} blocking data issue(s) need recovery.")
        elif warning_count:
            st.warning(f"{warning_count} quality warning(s) need human review.")
        else:
            st.success("Dataset checks have no unresolved quality issue.")
        if anomalies is not None:
            st.info(f"{flagged_count:,} record(s) are flagged by {RULESET_VERSION} for review—not declared fraud.")
        if assessment.is_blocked:
            st.button("Open data quality", type="primary", width="stretch", on_click=navigate_to, args=("Upload Data",))
        else:
            st.button("Open portfolio", type="primary", width="stretch", on_click=navigate_to, args=("Dashboard",))
            st.button("Review risk flags", width="stretch", on_click=navigate_to, args=("Anomaly Detection",))


def page_upload() -> None:
    st.title("Upload Data")
    st.caption(
        "Bring one bounded CSV into a traceable evidence workflow. PulseIQ separates source validation, "
        "business meaning, and fitness for use."
    )

    with st.container(key="data_intake"):
        st.header("Add an evidence source")
        c1, c2 = st.columns([0.62, 0.38])
        with c1:
            uploaded = st.file_uploader("Upload CSV", type=["csv"])
            if uploaded is not None:
                try:
                    ingested = ingest_csv(uploaded.getvalue(), filename=uploaded.name)
                    current_metadata = st.session_state.get("ingestion_metadata")
                    current_sha = current_metadata.sha256 if current_metadata is not None else None
                    if ingested.metadata.sha256 != current_sha:
                        st.session_state.data = ingested.dataframe
                        st.session_state.data_source = ingested.metadata.filename
                        st.session_state.data_currency = None
                        st.session_state.dataset_currency_choice = "Not confirmed"
                        st.session_state.ingestion_metadata = ingested.metadata
                        st.session_state.header_mappings = ingested.header_mappings
                        st.session_state.model_bundle = None
                        st.success(f"Validated and loaded {ingested.metadata.filename}.")
                except UploadRejected as exc:  # pragma: no cover - Streamlit upload interaction
                    st.error(f"Upload blocked [{exc.code.value}]: {exc.user_message}")
                    st.info(exc.recovery)
            if st.button("Use sample business data", type="primary", on_click=set_demo_data):
                st.success("Demo dataset loaded.")
        with c2:
            st.markdown("**What PulseIQ checks first**")
            st.write("File bounds, encoding, delimiter, duplicate headers, row shape, and unsafe content.")
            st.caption(
                f"Prototype limit · {DEFAULT_UPLOAD_POLICY.max_bytes // (1024 * 1024)} MB · "
                f"{DEFAULT_UPLOAD_POLICY.max_rows:,} rows · {DEFAULT_UPLOAD_POLICY.max_columns:,} columns"
            )

    data = get_data()
    if data is None:
        render_workflow_steps(
            "Evidence intake",
            "No source is active",
            (
                ("Upload source", "Choose a bounded CSV or the synthetic demo.", "is-current"),
                ("Confirm meaning", "Map concepts, units, period, and currency.", "is-pending"),
                ("Review quality", "Inspect blockers, warnings, and recovery.", "is-pending"),
                ("Use evidence", "Downstream work stays unavailable until ready.", "is-pending"),
            ),
        )
        require_dataset_message()
        return

    metadata = st.session_state.get("ingestion_metadata")
    header_mappings = st.session_state.get("header_mappings", ())
    if metadata is not None:
        delimiter_name = "tab" if metadata.delimiter == "\t" else repr(metadata.delimiter)
        st.info(
            f"Detected {metadata.encoding} encoding and {delimiter_name} delimiter · "
            f"{metadata.size_bytes:,} bytes · source SHA-256 {metadata.sha256[:12]}…"
        )

    assessment = assess_dataset(data)
    warning_count = sum(issue.severity is IssueSeverity.WARN for issue in assessment.issues)
    currency_choice = st.session_state.get("dataset_currency_choice", "Not confirmed")
    mapping_review_required = bool(header_mappings) or currency_choice == "Not confirmed"
    if assessment.is_blocked:
        quality_stage = ("Review quality", "Blocking issues require recovery.", "is-blocked")
        use_stage = ("Use evidence", "Blocked capabilities remain unavailable.", "is-blocked")
        workflow_summary = "Recovery is required"
    elif warning_count:
        quality_stage = ("Review quality", f"{warning_count} warning(s) remain visible.", "is-warning")
        use_stage = (
            "Use evidence",
            "Available only with the displayed cautions." if not mapping_review_required else "Confirm meaning first.",
            "is-warning",
        )
        workflow_summary = "Usable with cautions"
    else:
        quality_stage = ("Review quality", "Ready · supported checks passed.", "is-ready")
        use_stage = (
            "Use evidence",
            "Confirm meaning first."
            if mapping_review_required
            else "Ready · supported prototype workflows are available.",
            "is-warning" if mapping_review_required else "is-ready",
        )
        workflow_summary = "Meaning still needs review" if mapping_review_required else "Evidence is ready"

    render_workflow_steps(
        "Evidence intake",
        workflow_summary,
        (
            ("Upload source", f"Loaded · {st.session_state.data_source}", "is-ready"),
            (
                "Confirm meaning",
                "Review suggestions and currency."
                if mapping_review_required
                else "Confirmed · semantic context is set.",
                "is-current" if mapping_review_required else "is-ready",
            ),
            quality_stage,
            use_stage,
        ),
    )

    if header_mappings:
        suggestions = suggest_semantic_mappings(header_mappings)
        st.header("Confirm meaning")
        st.caption("Critical concepts remain suggestions until a human confirms their meaning, unit, and period.")
        mapping_table = pd.DataFrame(
            [
                {
                    "Source column": item.source_column,
                    "Normalized field": item.normalized_column,
                    "Suggested concept": item.suggested_concept.value if item.suggested_concept else "Unmapped",
                    "Confidence": f"{item.confidence:.0%}" if item.confidence else "—",
                    "Confirmation": "Required" if item.confirmation_required else "Not applicable",
                }
                for item in suggestions
            ]
        )
        render_semantic_table("Source header and concept suggestions", mapping_table)

    currency_options = ["Not confirmed", "NGN", "GHS", "KES", "RWF", "USD"]
    selected_currency = st.selectbox(
        "Dataset currency",
        currency_options,
        key="dataset_currency_choice",
        help="Financial aggregates remain unavailable until one currency is confirmed.",
    )
    st.session_state.data_currency = None if selected_currency == "Not confirmed" else selected_currency

    st.header("Review quality")
    st.caption("Scores summarize observed evidence. Blocking issues and recovery instructions remain authoritative.")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Rows", f"{assessment.rows:,}")
    m2.metric("Columns", f"{assessment.columns:,}")
    m3.metric("Missing values", f"{int(data.isna().sum().sum()):,}")
    m4.metric("Duplicate rows", f"{int(data.duplicated().sum()):,}")
    m5.metric("Quality score", f"{assessment.composite_score:.1f}%")
    render_dataset_assessment(assessment)
    if assessment.issues:
        issue_export = pd.DataFrame(
            [
                {
                    "issue_code": issue.code,
                    "severity": issue.severity.value,
                    "dimension": issue.dimension.value,
                    "column": issue.column or "",
                    "affected_count": issue.count,
                    "message": issue.message,
                    "recovery": issue.recovery,
                    "affected_capabilities": "|".join(item.value for item in issue.affected_capabilities),
                    "definition_version": assessment.definition_version,
                }
                for issue in assessment.issues
            ]
        )
        st.download_button(
            "Download validation issues CSV",
            data=safe_csv_bytes(issue_export),
            file_name="pulseiq_validation_issues.csv",
            mime="text/csv",
        )
    st.header("Data preview")
    st.dataframe(data.head(50), width="stretch", height=360)


def page_dashboard() -> None:
    st.title("Portfolio")
    st.caption(
        "Read governed portfolio measures within an explicit evidence scope. Filters change the analytical view, "
        "not the underlying dataset version."
    )
    data = get_data()
    if data is None:
        require_dataset_message()
        return

    source_assessment = assess_dataset(data)
    render_trust_ribbon(
        source_assessment,
        source=st.session_state.get("data_source", "Active dataset"),
        mapping_review_required=bool(st.session_state.get("header_mappings")),
    )

    with st.container(key="portfolio_filters"):
        st.markdown("**Evidence scope**")
        f1, f2, f3 = st.columns(3)
        segment_options = ["All segments"]
        if "segment" in data.columns:
            segment_options.extend(sorted(str(value) for value in data["segment"].dropna().unique()))
        region_options = ["All regions"]
        if "region" in data.columns:
            region_options.extend(sorted(str(value) for value in data["region"].dropna().unique()))
        business_options = ["All business types"]
        if "business_type" in data.columns:
            business_options.extend(sorted(str(value) for value in data["business_type"].dropna().unique()))
        segment = f1.selectbox("Segment", segment_options)
        region = f2.selectbox("Region", region_options)
        business_type = f3.selectbox("Business type", business_options)

    portfolio = data
    if segment != "All segments":
        portfolio = portfolio[portfolio["segment"].astype(str) == segment]
    if region != "All regions":
        portfolio = portfolio[portfolio["region"].astype(str) == region]
    if business_type != "All business types":
        portfolio = portfolio[portfolio["business_type"].astype(str) == business_type]
    st.caption(f"Viewing {len(portfolio):,} of {len(data):,} source records.")
    if portfolio.empty:
        st.info("No records match this evidence scope. Broaden one or more portfolio filters.")
        return

    assessment = assess_dataset(portfolio)
    anomalies = detect_anomalies(portfolio) if assessment.can(DatasetCapability.RISK_RULE_EVALUATION) else None
    metrics = calculate_portfolio_metrics(
        portfolio,
        currency=st.session_state.get("data_currency"),
        anomaly_dataframe=anomalies,
        risk_rule_version=RULESET_VERSION if anomalies is not None else None,
    )

    st.header("Decision measures")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        render_governed_metric(metrics.metric(MetricId.TRANSACTION_VALUE))
    with m2:
        render_governed_metric(metrics.metric(MetricId.UNIQUE_CUSTOMERS))
    with m3:
        render_governed_metric(metrics.metric(MetricId.AVERAGE_TRANSACTION_VALUE))
    with m4:
        render_governed_metric(metrics.metric(MetricId.NON_DEFAULT_OUTCOME_SHARE))

    with st.expander("Operational evidence and metric definitions"):
        m5, m6, m7, m8 = st.columns(4)
        with m5:
            render_governed_metric(metrics.metric(MetricId.RECORDS_PROCESSED))
        with m6:
            render_governed_metric(metrics.metric(MetricId.HIGH_RISK_RECORDS))
        with m7:
            render_governed_metric(metrics.metric(MetricId.SUSPICIOUS_RECORDS))
        with m8:
            render_governed_metric(metrics.metric(MetricId.DATA_QUALITY_SCORE))

    st.header("Portfolio evidence")
    transaction_metric = metrics.metric(MetricId.TRANSACTION_VALUE)
    trend_column, attention_column = st.columns([1.35, 0.85])
    with trend_column:
        if transaction_metric.status is MetricStatus.AVAILABLE:
            transaction_trend = monthly_revenue(portfolio)
            fig = px.line(
                transaction_trend,
                x="month",
                y="transaction_amount",
                markers=True,
                title="Monthly transaction value",
            )
            fig.update_traces(line_width=3, marker_size=7)
            fig.update_layout(yaxis_title=f"Transaction value ({transaction_metric.currency})", xaxis_title="Month")
            st.plotly_chart(fig, width="stretch")
            render_chart_data_table("Monthly transaction value", transaction_trend)
        else:
            st.info("Transaction trend requires a confirmed amount, currency, and period.")

    with attention_column:
        if anomalies is not None and "risk_level" in anomalies.columns:
            risk = categorical_counts(anomalies, "risk_level").sort_values("records")
            fig = px.bar(
                risk,
                x="records",
                y="risk_level",
                orientation="h",
                color="risk_level",
                color_discrete_map={"High": "#B9382F", "Medium": "#976000", "Low": "#3154F5"},
                title=f"Rule priority ({RULESET_VERSION})",
            )
            fig.update_layout(xaxis_title="Records", yaxis_title="Priority", showlegend=False)
            st.plotly_chart(fig, width="stretch")
            render_chart_data_table(f"Rule priority ({RULESET_VERSION})", risk)
        else:
            st.info("Rule-priority evidence is unavailable for this dataset scope.")

    with st.container(key="portfolio_insights"):
        st.markdown("**Evidence-led observations**")
        for insight in build_metric_insights(metrics):
            st.write(f"- {insight}")

    with st.expander("Explore distributions and segment comparisons"):
        c1, c2 = st.columns(2)
        with c1:
            if metrics.metric(MetricId.NON_DEFAULT_OUTCOME_SHARE).status is MetricStatus.AVAILABLE:
                breakdown = default_breakdown(portfolio)
                fig = px.bar(breakdown, x="repayment_status", y="records", title="Recorded outcome breakdown")
                fig.update_layout(xaxis_title="Outcome", yaxis_title="Records")
                st.plotly_chart(fig, width="stretch")
                render_chart_data_table("Recorded outcome breakdown", breakdown)

            if metrics.metric(MetricId.UNIQUE_CUSTOMERS).status is MetricStatus.AVAILABLE and "segment" in portfolio:
                segments = categorical_counts(portfolio, "segment").head(8)
                fig = px.bar(segments, x="segment", y="records", title="Top customer segments")
                fig.update_layout(xaxis_title="Segment", yaxis_title="Records")
                st.plotly_chart(fig, width="stretch")
                render_chart_data_table("Top customer segments", segments)

        with c2:
            if transaction_metric.status is MetricStatus.AVAILABLE:
                fig = px.histogram(
                    portfolio,
                    x="transaction_amount",
                    nbins=38,
                    title="Transaction amount distribution",
                )
                fig.update_layout(xaxis_title="Transaction value", yaxis_title="Records")
                st.plotly_chart(fig, width="stretch")
                amounts = pd.to_numeric(portfolio["transaction_amount"], errors="coerce").dropna()
                distribution = (
                    pd.cut(amounts, bins=10, duplicates="drop")
                    .value_counts(sort=False)
                    .rename_axis("transaction_value_range")
                    .reset_index(name="records")
                )
                distribution["transaction_value_range"] = distribution["transaction_value_range"].astype(str)
                render_chart_data_table("Transaction amount distribution", distribution)

            summary = anomaly_summary(anomalies) if anomalies is not None else pd.DataFrame()
            if not summary.empty:
                category = summary.groupby("suspicious_category")["records"].sum().reset_index().sort_values("records")
                fig = px.bar(
                    category,
                    x="records",
                    y="suspicious_category",
                    orientation="h",
                    title="Suspicious activity by category",
                )
                fig.update_layout(xaxis_title="Records", yaxis_title="Issue")
                st.plotly_chart(fig, width="stretch")
                render_chart_data_table("Suspicious activity by category", category)


def page_prediction() -> None:
    st.title("Model exploration")
    data = get_data()
    if data is None:
        require_dataset_message()
        return

    assessment = assess_dataset(data)
    if not require_dataset_capability(assessment, DatasetCapability.MODEL_EXPLORATION):
        return

    eligibility = assess_model_eligibility(data)
    e1, e2, e3 = st.columns(3)
    e1.metric("Eligible outcome rows", f"{eligibility.eligible_rows:,}")
    e2.metric("Excluded outcome rows", f"{eligibility.excluded_target_rows:,}")
    e3.metric(
        "Outcome classes",
        ", ".join(f"{label}: {count:,}" for label, count in eligibility.class_counts) or "Not available",
    )
    if eligibility.status is EligibilityStatus.BLOCKED:
        st.error("Model exploration is blocked by the eligibility checks below.")
    else:
        st.success("Dataset passes the bounded demonstration eligibility checks.")
    for issue in eligibility.issues:
        message = f"{issue.message} Recovery: {issue.recovery}"
        if issue.severity.value == "block":
            st.error(message)
        else:
            st.warning(message)
    with st.expander("Feature eligibility evidence"):
        render_semantic_table(
            "Feature eligibility evidence",
            pd.DataFrame(
                [
                    {
                        "Feature": profile.column,
                        "Kind": profile.kind,
                        "Valid": profile.valid_count,
                        "Missing": profile.missing_count,
                        "Invalid": profile.invalid_count,
                        "Unique": profile.unique_count,
                    }
                    for profile in eligibility.profiles
                ]
            ),
        )
    if eligibility.status is EligibilityStatus.BLOCKED:
        return

    if st.button("Train prediction models", type="primary"):
        with st.spinner("Training Logistic Regression, Random Forest, and Decision Tree models..."):
            try:
                st.session_state.model_bundle = train_models(data)
            except ModelEligibilityError as exc:
                st.error(str(exc))

    bundle: ModelBundle | None = st.session_state.get("model_bundle")
    if bundle is None:
        st.info("Train the models to view evaluation metrics and score a customer.")
        return

    st.warning(
        "Demonstration model only · unapproved · uncalibrated output · never use as the sole basis for a decision."
    )
    st.header(f"Selected demonstration model: {bundle.name}")
    st.caption("Candidates were selected on a validation split. The metrics below come from a separate final holdout.")
    leaderboard = pd.DataFrame(bundle.leaderboard)
    render_semantic_table("Candidate validation metrics", leaderboard)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Accuracy", f"{bundle.metrics['accuracy']:.2f}")
    m2.metric("Precision", f"{bundle.metrics['precision']:.2f}")
    m3.metric("Recall", f"{bundle.metrics['recall']:.2f}")
    m4.metric("F1-score", f"{bundle.metrics['f1_score']:.2f}")
    m5.metric("ROC-AUC", f"{bundle.metrics['roc_auc']:.2f}")
    m6, m7, m8 = st.columns(3)
    m6.metric("PR-AUC", f"{bundle.metrics['pr_auc']:.2f}")
    m7.metric("Brier score (lower is better)", f"{bundle.metrics['brier_score']:.3f}")
    m8.metric("Log loss (lower is better)", f"{bundle.metrics['log_loss']:.3f}")

    with st.expander("Model run provenance and limitations"):
        st.write(f"Run: {bundle.provenance.run_id}")
        st.write(f"Dataset: {bundle.provenance.dataset_reference}")
        st.write(f"Target: {bundle.provenance.target_definition}")
        st.write(f"Features: {bundle.provenance.feature_definition}")
        st.write(f"Split: {bundle.provenance.split_strategy}")
        st.write(
            f"Rows — train: {bundle.provenance.train_rows:,}; validation: "
            f"{bundle.provenance.validation_rows:,}; holdout: {bundle.provenance.test_rows:,}."
        )
        st.write("Displayed output is not calibrated and no validated model-faithful local explanation is available.")

    st.header("Confusion matrix")
    matrix = pd.DataFrame(
        bundle.confusion_matrix,
        index=["Actual repaid", "Actual defaulted"],
        columns=["Predicted repaid", "Predicted defaulted"],
    )
    render_semantic_table("Final holdout confusion matrix", matrix.reset_index(names="Actual outcome"))

    st.header("Score a customer")
    with st.form("score_customer_form"):
        c1, c2, c3 = st.columns(3)
        values = {
            "income": c1.number_input("Monthly income", min_value=0.0, value=220000.0, step=10000.0),
            "loan_amount": c2.number_input("Loan amount", min_value=0.0, value=180000.0, step=10000.0),
            "repayment_history_score": c3.slider("Repayment history score", 0, 100, 72),
            "existing_debt": c1.number_input("Existing debt", min_value=0.0, value=35000.0, step=5000.0),
            "transaction_frequency": c2.number_input(
                "Monthly transaction frequency", min_value=0.0, value=24.0, step=1.0
            ),
            "account_age_months": c3.number_input("Account age in months", min_value=0, value=28, step=1),
            "employment_status": c1.selectbox(
                "Employment status", ["Salaried", "Self-employed", "Contract", "Informal", "Unemployed"]
            ),
            "segment": c2.selectbox("Segment", ["Retail", "Market Trader", "SME", "Agriculture", "Services"]),
            "business_type": c3.selectbox(
                "Business type", ["Shop", "Transport", "Food", "Education", "Health", "Fintech Agent"]
            ),
            "region": c1.selectbox("Region", ["Lagos", "Abuja", "Kano", "Accra", "Kumasi", "Nairobi", "Kigali"]),
        }
        submitted = st.form_submit_button("Predict default risk")

    if submitted:
        result = score_customer(bundle, values)
        r1, r2, r3 = st.columns(3)
        r1.metric("Uncalibrated model output", f"{result['model_score_percent']:.1f}%")
        r2.metric("Routing", result["routing"])
        r3.metric("Explanation", result["explanation_status"])
        st.warning(result["score_semantics"])
        st.info(result["explanation"])


def page_anomaly() -> None:
    st.title("Risk review")
    st.caption(
        "Prioritize rule evidence for human review. A flag is not a fraud finding, case disposition, or final decision."
    )
    data = get_data()
    if data is None:
        require_dataset_message()
        return

    assessment = assess_dataset(data)
    if not require_dataset_capability(assessment, DatasetCapability.RISK_RULE_EVALUATION):
        return

    render_trust_ribbon(
        assessment,
        source=st.session_state.get("data_source", "Active dataset"),
        mapping_review_required=bool(st.session_state.get("header_mappings")),
    )

    anomalies = detect_anomalies(data)
    summary = anomaly_summary(anomalies)
    coverage = rule_coverage(anomalies)
    flagged = anomalies[anomalies["is_suspicious"]].sort_values("anomaly_score", ascending=False)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Flagged records", f"{len(flagged):,}")
    c2.metric("Flagged share", f"{len(flagged) / len(anomalies):.1%}" if len(anomalies) else "Not available")
    c3.metric("High-priority flags", f"{int((flagged['risk_level'] == 'High').sum()):,}")
    c4.metric("Top anomaly score", f"{flagged['anomaly_score'].max() if not flagged.empty else 0:.1f}")

    incomplete_evaluations = int(coverage["not_evaluated_records"].sum())
    if incomplete_evaluations:
        st.warning(
            f"{incomplete_evaluations:,} record-rule evaluations were not evaluated because source evidence "
            "was missing or invalid. Clear results do not include those evaluations."
        )
    st.header("Rule evidence coverage")
    st.caption(f"Ruleset {RULESET_VERSION}. Coverage is shown separately from trigger counts.")
    render_semantic_table(
        f"Rule evidence coverage for {RULESET_VERSION}",
        coverage[
            [
                "rule_label",
                "evaluated_records",
                "not_evaluated_records",
                "triggered_records",
                "coverage_percent",
            ]
        ].rename(
            columns={
                "rule_label": "Rule",
                "evaluated_records": "Evaluated",
                "not_evaluated_records": "Not evaluated",
                "triggered_records": "Triggered",
                "coverage_percent": "Coverage %",
            }
        ),
    )

    if not summary.empty:
        fig = px.bar(
            summary,
            x="records",
            y="suspicious_category",
            color="risk_level",
            orientation="h",
            title="Suspicious records by rule",
        )
        fig.update_layout(xaxis_title="Records", yaxis_title="Rule")
        st.plotly_chart(fig, width="stretch")
        render_chart_data_table("Suspicious records by rule", summary)

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
            "rules_evaluated_count",
            "rules_not_evaluated_count",
            "not_evaluated_rule_ids",
            "anomaly_notes",
        ]
        if column in flagged.columns
    ]
    st.header("Review queue")
    st.caption("Filter the queue without changing the immutable rule output or its evidence fields.")
    with st.container(key="risk_filters"):
        f1, f2, f3 = st.columns(3)
        priority = f1.selectbox("Priority", ["All priorities", "High", "Medium", "Low"])
        rule_options = ["All rules", *sorted(str(value) for value in flagged["suspicious_category"].unique())]
        selected_rule = f2.selectbox("Triggered rule", rule_options)
        query = f3.text_input("Find customer or transaction", placeholder="Customer or transaction ID")

    review_rows = flagged
    if priority != "All priorities":
        review_rows = review_rows[review_rows["risk_level"] == priority]
    if selected_rule != "All rules":
        review_rows = review_rows[review_rows["suspicious_category"] == selected_rule]
    if query.strip():
        search_fields = [column for column in ("customer_id", "transaction_id") if column in review_rows]
        matches = pd.Series(False, index=review_rows.index)
        for column in search_fields:
            matches |= review_rows[column].astype(str).str.contains(query.strip(), case=False, regex=False, na=False)
        review_rows = review_rows[matches]

    st.caption(f"Showing {min(len(review_rows), 250):,} of {len(review_rows):,} matching flagged records.")
    if review_rows.empty:
        st.info("No flagged records match these filters. Broaden the priority, rule, or identifier search.")
    else:
        st.dataframe(review_rows[display_cols].head(250), width="stretch", height=430)
    st.download_button(
        "Download filtered review queue CSV",
        data=safe_csv_bytes(review_rows),
        file_name="pulseiq_filtered_review_queue.csv",
        mime="text/csv",
    )


def page_report() -> None:
    st.title("Reports")
    st.caption(
        "Package one governed evidence snapshot with its definitions, unavailable states, rule provenance, and "
        "decision-use disclosures."
    )
    data = get_data()
    if data is None:
        require_dataset_message()
        return

    assessment = assess_dataset(data)
    render_trust_ribbon(
        assessment,
        source=st.session_state.get("data_source", "Active dataset"),
        mapping_review_required=bool(st.session_state.get("header_mappings")),
    )
    anomalies = detect_anomalies(data) if assessment.can(DatasetCapability.RISK_RULE_EVALUATION) else pd.DataFrame()
    metrics = calculate_portfolio_metrics(
        data,
        currency=st.session_state.get("data_currency"),
        anomaly_dataframe=anomalies if not anomalies.empty else None,
        risk_rule_version=RULESET_VERSION if not anomalies.empty else None,
    )
    bundle: ModelBundle | None = st.session_state.get("model_bundle")
    insights = list(build_metric_insights(metrics))
    if not anomalies.empty:
        coverage = rule_coverage(anomalies)
        evaluated = int(coverage["evaluated_records"].sum())
        possible = evaluated + int(coverage["not_evaluated_records"].sum())
        insights.append(
            f"Rule evidence coverage is {evaluated:,} of {possible:,} record-rule evaluations under "
            f"{RULESET_VERSION}; non-evaluated rules are not clear results."
        )
    if bundle is not None:
        insights.append(
            f"Model run {bundle.provenance.run_id} is an unapproved demonstration selected on validation and "
            "evaluated on a separate holdout; its output is uncalibrated and requires human review."
        )

    start = time.perf_counter()
    pdf = build_report_pdf(
        data,
        metrics,
        anomalies,
        insights,
        model_name=bundle.name if bundle else None,
        model_metrics=bundle.metrics if bundle else None,
        model_run_id=bundle.provenance.run_id if bundle else None,
        model_split_strategy=bundle.provenance.split_strategy if bundle else None,
        model_probability_status=bundle.provenance.probability_status if bundle else None,
    )
    elapsed = time.perf_counter() - start
    html = build_report_html(metrics, insights, anomalies)

    governed_metric_ids = (
        MetricId.TRANSACTION_VALUE,
        MetricId.UNIQUE_CUSTOMERS,
        MetricId.AVERAGE_TRANSACTION_VALUE,
        MetricId.NON_DEFAULT_OUTCOME_SHARE,
        MetricId.RECORDS_PROCESSED,
        MetricId.HIGH_RISK_RECORDS,
        MetricId.SUSPICIOUS_RECORDS,
        MetricId.DATA_QUALITY_SCORE,
    )
    unavailable_count = sum(
        metrics.metric(metric_id).status is MetricStatus.UNAVAILABLE for metric_id in governed_metric_ids
    )
    definition_stage = (
        (
            "Resolve definitions",
            f"Warning · {unavailable_count} governed measure(s) remain unavailable.",
            "is-warning",
        )
        if unavailable_count
        else (
            "Resolve definitions",
            "Ready · governed measures include provenance.",
            "is-ready",
        )
    )
    render_workflow_steps(
        "Report delivery",
        "Ready with visible cautions" if unavailable_count or assessment.issues else "Evidence package is ready",
        (
            ("Bind snapshot", f"Loaded · {len(data):,} immutable source rows.", "is-ready"),
            definition_stage,
            ("Review disclosures", "Ready · decision-use limits are included.", "is-ready"),
            ("Download evidence", "Ready · accessible HTML and PDF are prepared.", "is-ready"),
        ),
    )

    st.header("Report preview")
    context_column, insight_column = st.columns([0.85, 1.15])
    with context_column, st.container(key="report_context"):
        st.markdown("**Bound evidence**")
        render_semantic_table(
            "Report evidence context",
            pd.DataFrame(
                [
                    {"Evidence": "Source", "Value": st.session_state.get("data_source", "Active dataset")},
                    {"Evidence": "Rows", "Value": f"{len(data):,}"},
                    {"Evidence": "Quality definition", "Value": assessment.definition_version},
                    {
                        "Evidence": "Rule evidence",
                        "Value": RULESET_VERSION if not anomalies.empty else "Not included",
                    },
                    {
                        "Evidence": "Model evidence",
                        "Value": bundle.provenance.run_id if bundle is not None else "Not included",
                    },
                ]
            ),
        )
    with insight_column, st.container(key="portfolio_insights"):
        st.markdown("**Included observations and disclosures**")
        for insight in insights:
            st.write(f"- {insight}")

    st.header("Download evidence package")
    with st.container(key="report_delivery"):
        d1, d2, d3 = st.columns([0.42, 1, 1])
        with d1:
            st.metric("Prepared in", f"{elapsed:.2f}s")
        with d2:
            st.download_button(
                "Download accessible HTML report",
                data=html.encode("utf-8"),
                file_name="pulseiq_governed_portfolio_report.html",
                mime="text/html",
                type="primary",
                width="stretch",
            )
        with d3:
            st.download_button(
                "Download PulseIQ report PDF",
                data=pdf,
                file_name="pulseiq_business_intelligence_report.pdf",
                mime="application/pdf",
                width="stretch",
            )
        st.caption("HTML is the accessible primary format. PDF is a fixed-layout companion, not the only record.")


def page_assistant() -> None:
    st.title("Insight Assistant")
    data = get_data()
    if data is None:
        require_dataset_message()
        return

    assessment = assess_dataset(data)
    anomalies = detect_anomalies(data) if assessment.can(DatasetCapability.RISK_RULE_EVALUATION) else pd.DataFrame()
    metrics = calculate_portfolio_metrics(
        data,
        currency=st.session_state.get("data_currency"),
        anomaly_dataframe=anomalies if not anomalies.empty else None,
        risk_rule_version=RULESET_VERSION if not anomalies.empty else None,
    )
    bundle: ModelBundle | None = st.session_state.get("model_bundle")

    quick = st.selectbox(
        "Question",
        [
            "What is the biggest risk?",
            "What should the business do next?",
            "Why was this transaction flagged?",
            "How good is the data quality?",
            "How did the model perform?",
            "What is the transaction value picture?",
        ],
    )
    custom = st.text_input("Ask your own question")
    question = custom or quick
    st.write(answer_question(question, data, metrics, anomalies, bundle.metrics if bundle else None))


def page_about() -> None:
    st.title("About PulseIQ")
    st.write(
        "PulseIQ Africa is a governed decision-intelligence workspace for SME finance and risk teams. "
        "This interface is a demonstration shell over verified domain foundations; it is not yet production "
        "lending infrastructure and does not automate final credit decisions."
    )
    c1, c2 = st.columns(2)
    with c1:
        st.header("Tech stack")
        st.write("- Streamlit")
        st.write("- Python")
        st.write("- pandas and numpy")
        st.write("- Plotly")
        st.write("- scikit-learn")
        st.write("- ReportLab")
    with c2:
        st.header("Production integration in progress")
        st.write("- Secure identity and workspace API shell")
        st.write("- Persisted import, mapping, validation, and activation workflows")
        st.write("- Governed risk cases, decisions, and model approval")
        st.write("- Operational telemetry and delivery controls")
        st.write("- Manual assistive-technology and deployment verification")


def main() -> None:
    init_state()
    theme_mode = st.session_state.get("theme_mode")
    if theme_mode not in THEME_MODES:
        theme_mode = "System"
        st.session_state.theme_mode = theme_mode
    apply_page_style(theme_mode)
    render_theme_switcher()
    st.markdown('<div id="main-content" tabindex="-1"></div>', unsafe_allow_html=True)
    page = sidebar_nav()
    mobile_navigation(page, on_change=navigate_from_mobile)
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
