"""Streamlit integration tests for dataset validation states."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from pulseiq.data import load_demo_data

APP_PATH = Path(__file__).resolve().parents[2] / "app.py"


def test_home_upload_call_to_action_changes_the_workspace_page() -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=10)

    app.run()
    next(button for button in app.button if button.label == "Go to upload page").click().run()

    assert not app.exception
    assert any(title.value == "Upload Data" for title in app.title)


def test_mobile_navigation_changes_the_shared_workspace_page() -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=10)

    app.run()
    next(radio for radio in app.radio if radio.label == "Primary navigation").set_value("Upload Data").run()

    assert not app.exception
    assert any(title.value == "Upload Data" for title in app.title)


def test_upload_page_announces_an_empty_dataset_as_blocked() -> None:
    """An empty upload has a textual blocking state and a zero score."""

    app = AppTest.from_file(APP_PATH, default_timeout=10)
    app.session_state["data"] = pd.DataFrame()
    app.session_state["data_source"] = "empty.csv"
    app.session_state["model_bundle"] = None

    app.run()
    next(radio for radio in app.radio if radio.label == "Workspace").set_value("Upload Data").run()

    assert not app.exception
    assert any("blocked" in message.value.lower() for message in app.error)
    assert any(metric.label == "Quality score" and metric.value == "0.0%" for metric in app.metric)


def test_prediction_page_hides_training_when_model_inputs_are_missing() -> None:
    """The UI must not invoke a model path that would fill silent defaults."""

    app = AppTest.from_file(APP_PATH, default_timeout=10)
    app.session_state["data"] = pd.DataFrame(
        {
            "customer_id": ["CUST-1"],
            "date": ["2026-01-01"],
            "transaction_amount": [1200],
            "defaulted": [0],
        }
    )
    app.session_state["data_source"] = "incomplete.csv"
    app.session_state["model_bundle"] = None

    app.run()
    next(radio for radio in app.radio if radio.label == "Workspace").set_value("Prediction").run()

    assert not app.exception
    assert any("model exploration is blocked" in message.value.lower() for message in app.error)
    assert all(button.label != "Train prediction models" for button in app.button)


def test_prediction_page_exposes_model_eligibility_before_training() -> None:
    """A schema-complete but statistically insufficient dataset cannot train."""

    dataframe = load_demo_data().head(20).copy()
    dataframe["defaulted"] = [0, 1] * 10
    app = AppTest.from_file(APP_PATH, default_timeout=10)
    app.session_state["data"] = dataframe
    app.session_state["data_source"] = "small.csv"
    app.session_state["model_bundle"] = None

    app.run()
    next(radio for radio in app.radio if radio.label == "Workspace").set_value("Prediction").run()

    assert not app.exception
    assert any("eligibility" in message.value.lower() for message in app.error)
    assert all(button.label != "Train prediction models" for button in app.button)


def test_anomaly_page_blocks_rules_when_evidence_fields_are_missing() -> None:
    """The UI cannot run rules whose required evidence would be defaulted."""

    app = AppTest.from_file(APP_PATH, default_timeout=10)
    app.session_state["data"] = pd.DataFrame(
        {
            "customer_id": ["CUST-1"],
            "date": ["2026-01-01"],
            "transaction_amount": [1200],
        }
    )
    app.session_state["data_source"] = "incomplete.csv"
    app.session_state["model_bundle"] = None

    app.run()
    next(radio for radio in app.radio if radio.label == "Workspace").set_value("Anomaly Detection").run()

    assert not app.exception
    assert any("risk rule evaluation is blocked" in message.value.lower() for message in app.error)
    assert not app.download_button


def test_anomaly_page_exposes_a_filterable_human_review_queue() -> None:
    """Rule flags remain review evidence and can be narrowed without changing source output."""

    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.session_state["data"] = load_demo_data()
    app.session_state["data_source"] = "Built-in demo loan and transaction data"
    app.session_state["data_currency"] = "NGN"
    app.session_state["model_bundle"] = None

    app.run(timeout=20)
    next(radio for radio in app.radio if radio.label == "Workspace").set_value("Anomaly Detection").run(timeout=20)

    assert not app.exception
    assert any(selectbox.label == "Priority" for selectbox in app.selectbox)
    assert any(selectbox.label == "Triggered rule" for selectbox in app.selectbox)
    assert any(field.label == "Find customer or transaction" for field in app.text_input)
    assert any(button.label == "Download filtered review queue CSV" for button in app.download_button)


def test_dashboard_renders_missing_transaction_value_as_not_available() -> None:
    """The dashboard cannot present a missing amount dependency as NGN zero revenue."""

    app = AppTest.from_file(APP_PATH, default_timeout=10)
    app.session_state["data"] = pd.DataFrame(
        {
            "customer_id": ["CUST-1"],
            "date": ["2026-01-01"],
            "defaulted": [0],
        }
    )
    app.session_state["data_source"] = "incomplete.csv"
    app.session_state["data_currency"] = "NGN"
    app.session_state["model_bundle"] = None

    app.run()
    next(radio for radio in app.radio if radio.label == "Workspace").set_value("Dashboard").run()

    assert not app.exception
    assert any(metric.label == "Total transaction value" and metric.value == "Not available" for metric in app.metric)
    assert all(metric.label != "Total revenue" for metric in app.metric)


def test_report_page_offers_accessible_html_when_metrics_are_unavailable() -> None:
    """Report generation preserves unavailable states in both supported formats."""

    app = AppTest.from_file(APP_PATH, default_timeout=15)
    app.session_state["data"] = pd.DataFrame({"customer_id": ["CUST-1"], "date": ["2026-01-01"]})
    app.session_state["data_source"] = "incomplete.csv"
    app.session_state["data_currency"] = "NGN"
    app.session_state["model_bundle"] = None

    app.run()
    next(radio for radio in app.radio if radio.label == "Workspace").set_value("Report").run()

    assert not app.exception
    assert any(button.label == "Download accessible HTML report" for button in app.download_button)
    assert any(button.label == "Download PulseIQ report PDF" for button in app.download_button)
    assert any(metric.label == "Prepared in" for metric in app.metric)


def test_demo_dashboard_renders_governed_metrics_without_legacy_labels() -> None:
    """The representative happy path renders all governed dashboard metrics."""

    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.session_state["data"] = load_demo_data()
    app.session_state["data_source"] = "Built-in demo loan and transaction data"
    app.session_state["data_currency"] = "NGN"
    app.session_state["model_bundle"] = None

    app.run(timeout=20)
    next(radio for radio in app.radio if radio.label == "Workspace").set_value("Dashboard").run(timeout=20)

    assert not app.exception
    assert any(metric.label == "Total transaction value" and metric.value != "Not available" for metric in app.metric)
    assert any(
        metric.label == "Suspicious records (rules)" and metric.value != "Not available" for metric in app.metric
    )
    assert any(selectbox.label == "Segment" for selectbox in app.selectbox)
    assert any(selectbox.label == "Region" for selectbox in app.selectbox)
    assert any(selectbox.label == "Business type" for selectbox in app.selectbox)
    assert all(metric.label not in {"Total revenue", "Repayment rate"} for metric in app.metric)
