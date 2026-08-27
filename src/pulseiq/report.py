"""PDF report generation for PulseIQ Africa."""

from __future__ import annotations

from collections.abc import Sequence
from html import escape as html_escape
from io import BytesIO

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .anomaly import RULESET_VERSION, rule_coverage
from .portfolio_metrics import MetricStatus, MetricValue, PortfolioMetrics


def build_report_html(
    metrics: PortfolioMetrics,
    insights: list[str],
    anomaly_df: pd.DataFrame | None = None,
) -> str:
    """Build the accessible primary report representation."""

    rows: list[str] = []
    for metric in metrics.metrics:
        period = (
            f"{metric.period.start.isoformat()} to {metric.period.end.isoformat()}"
            if metric.period
            else "Not specified"
        )
        interpretation = ""
        if metric.status is MetricStatus.UNAVAILABLE:
            interpretation = f"{metric.unavailable_reason} Recovery: {metric.recovery}"
        logic = f"; logic {metric.logic_version}" if metric.logic_version else ""
        rows.append(
            "<tr>"
            f'<th scope="row">{html_escape(metric.label)}</th>'
            f"<td>{html_escape(_metric_display_value(metric))}</td>"
            f"<td>{html_escape(metric.unit)}</td>"
            f"<td>{html_escape(period)}</td>"
            f"<td>{html_escape(metric.quality_status.value)}</td>"
            f"<td>{html_escape(metric.definition_version + logic)}</td>"
            f"<td>{html_escape(interpretation)}</td>"
            "</tr>"
        )
    insight_items = "".join(f"<li>{html_escape(insight)}</li>" for insight in insights)
    coverage_section = ""
    if anomaly_df is not None and not anomaly_df.empty:
        coverage = rule_coverage(anomaly_df)
        coverage_rows = "".join(
            "<tr>"
            f'<th scope="row">{html_escape(str(row["rule_label"]))}</th>'
            f"<td>{int(row['evaluated_records']):,}</td>"
            f"<td>{int(row['not_evaluated_records']):,}</td>"
            f"<td>{int(row['triggered_records']):,}</td>"
            f"<td>{float(row['coverage_percent']):.1f}%</td>"
            "</tr>"
            for _, row in coverage.iterrows()
        )
        coverage_section = (
            '<section aria-labelledby="rule-coverage"><h2 id="rule-coverage">Rule evidence coverage</h2>'
            f"<p>Ruleset {html_escape(RULESET_VERSION)}. A not-evaluated result is not a clear result.</p>"
            "<table><caption>Evaluation coverage by rule</caption><thead><tr>"
            '<th scope="col">Rule</th><th scope="col">Evaluated</th><th scope="col">Not evaluated</th>'
            '<th scope="col">Triggered</th><th scope="col">Coverage</th></tr></thead>'
            f"<tbody>{coverage_rows}</tbody></table></section>"
        )
    generated_at = metrics.generated_at.isoformat()
    return (
        "<!doctype html>"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>PulseIQ governed portfolio report</title></head><body><main>"
        "<h1>PulseIQ governed portfolio report</h1>"
        "<p><strong>Demonstration only.</strong> This report supports review and must not be used as the sole basis "
        "for a credit or other significant decision.</p>"
        f"<p>Generated: {html_escape(generated_at)}. Dataset: {html_escape(metrics.dataset_reference)}.</p>"
        '<section aria-labelledby="metric-summary"><h2 id="metric-summary">Metric summary</h2>'
        "<table><caption>Governed metric summary</caption><thead><tr>"
        '<th scope="col">Metric</th><th scope="col">Value</th><th scope="col">Unit</th>'
        '<th scope="col">Period</th><th scope="col">Quality</th><th scope="col">Definition</th>'
        '<th scope="col">Interpretation and recovery</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></section>{coverage_section}"
        '<section aria-labelledby="insights"><h2 id="insights">Review notes</h2>'
        f"<ul>{insight_items}</ul></section></main></body></html>"
    )


def _metric_display_value(metric: MetricValue) -> str:
    """Format a metric without converting unavailable status into numeric zero."""

    if metric.status is MetricStatus.UNAVAILABLE or metric.value is None:
        return "Not available"
    if metric.unit == "currency":
        return f"{metric.currency} {float(metric.value):,.0f}"
    if metric.unit == "percent":
        return f"{float(metric.value):.1f}%"
    if isinstance(metric.value, int):
        return f"{metric.value:,}"
    return str(metric.value)


def _p(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(html_escape(str(text)), style)


def build_report_pdf(
    df: pd.DataFrame,
    metrics: PortfolioMetrics,
    anomaly_df: pd.DataFrame,
    insights: list[str],
    model_name: str | None = None,
    model_metrics: dict[str, float] | None = None,
    model_run_id: str | None = None,
    model_split_strategy: str | None = None,
    model_probability_status: str | None = None,
) -> bytes:
    """Build a downloadable PDF report from the current dashboard state."""

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.62 * inch,
        leftMargin=0.62 * inch,
        topMargin=0.58 * inch,
        bottomMargin=0.58 * inch,
        title="PulseIQ Business Intelligence Report",
    )

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "PulseTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#102033"),
        spaceAfter=10,
    )
    h2 = ParagraphStyle(
        "PulseHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#0D5C63"),
        spaceBefore=12,
        spaceAfter=6,
    )
    body = ParagraphStyle(
        "PulseBody", parent=styles["BodyText"], fontSize=9.5, leading=13, textColor=colors.HexColor("#182B3A")
    )
    small = ParagraphStyle("PulseSmall", parent=body, fontSize=8.5, leading=11)

    story: list[object] = []
    story.append(_p("PulseIQ Business Intelligence Report", title))
    story.append(_p("Governed decision-support summary for SME, fintech, and portfolio review workflows.", body))
    story.append(_p("Demonstration only. Do not use as the sole basis for a significant credit decision.", body))
    story.append(_p(f"Dataset: {metrics.dataset_reference}; generated: {metrics.generated_at.isoformat()}.", small))
    story.append(Spacer(1, 0.12 * inch))

    summary_rows: list[list[object]] = [["Metric", "Value", "Definition"]]
    for metric in metrics.metrics:
        summary_rows.append([metric.label, _metric_display_value(metric), metric.definition_version])
    story.append(_p("Dataset Summary", h2))
    story.append(_table(summary_rows, widths=[2.2 * inch, 1.5 * inch, 2.5 * inch]))

    story.append(_p("Key Insights", h2))
    for insight in insights:
        story.append(_p(f"- {insight}", body))

    story.append(_p("Prediction Model", h2))
    if model_metrics:
        model_rows = [["Model", model_name or "Selected classifier"]]
        for key in ["accuracy", "precision", "recall", "f1_score", "roc_auc", "pr_auc", "brier_score", "log_loss"]:
            if key in model_metrics:
                model_rows.append([key.replace("_", " ").title(), f"{model_metrics[key]:.3f}"])
        story.append(_table(model_rows, widths=[2.4 * inch, 3.8 * inch]))
        story.append(
            _p(
                "Demonstration model only. The candidate was selected on validation data and metrics are from a "
                "separate holdout. Output is uncalibrated and requires human review.",
                body,
            )
        )
        if model_run_id:
            story.append(_p(f"Run: {model_run_id}.", small))
        if model_split_strategy:
            story.append(_p(f"Split strategy: {model_split_strategy}.", small))
        if model_probability_status:
            story.append(_p(f"Output status: {model_probability_status}.", small))
    else:
        story.append(_p("The prediction model was not trained in this report session.", body))

    story.append(_p("Suspicious Activity", h2))
    flagged = anomaly_df[anomaly_df.get("is_suspicious", False)].copy() if not anomaly_df.empty else pd.DataFrame()
    if flagged.empty:
        story.append(_p("No suspicious records were flagged by the current rules.", body))
    else:
        grouped = (
            flagged.groupby(["suspicious_category", "risk_level"], dropna=False)
            .size()
            .reset_index(name="records")
            .sort_values("records", ascending=False)
            .head(8)
        )
        rows = [["Issue", "Risk", "Records"]]
        for _, row in grouped.iterrows():
            rows.append([row["suspicious_category"], row["risk_level"], f"{int(row['records']):,}"])
        story.append(_table(rows, widths=[3.3 * inch, 1.2 * inch, 1.3 * inch]))

    if not anomaly_df.empty:
        coverage = rule_coverage(anomaly_df)
        story.append(_p("Rule Evidence Coverage", h2))
        story.append(_p(f"Ruleset {RULESET_VERSION}. A not-evaluated result is not a clear result.", body))
        coverage_rows: list[list[object]] = [["Rule", "Evaluated", "Not evaluated", "Triggered", "Coverage"]]
        for _, row in coverage.iterrows():
            coverage_rows.append(
                [
                    row["rule_label"],
                    f"{int(row['evaluated_records']):,}",
                    f"{int(row['not_evaluated_records']):,}",
                    f"{int(row['triggered_records']):,}",
                    f"{float(row['coverage_percent']):.1f}%",
                ]
            )
        story.append(_table(coverage_rows, widths=[2.4 * inch, 0.8 * inch, 1.0 * inch, 0.8 * inch, 0.8 * inch]))

    story.append(_p("Recommendations", h2))
    recommendations = [
        "Resolve blocking metric and dataset issues before relying on dependent analysis.",
        "Review versioned rule evidence and preserve reviewer dispositions.",
        "Confirm metric definitions, currency, period, and source version before sharing.",
        "Use the model as decision support, not as the only approval rule.",
    ]
    for item in recommendations:
        story.append(_p(f"- {item}", body))

    story.append(Spacer(1, 0.14 * inch))
    story.append(_p("Generated by PulseIQ Africa. Demonstration only.", small))
    document.build(story)
    return buffer.getvalue()


def _table(rows: Sequence[Sequence[object]], widths: list[float]) -> Table:
    wrapped = [[_cell(value) for value in row] for row in rows]
    table = Table(wrapped, colWidths=widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D5C63")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("LEADING", (0, 0), (-1, -1), 10.5),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8E3E7")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F8F9")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _cell(value: object) -> Paragraph:
    styles = getSampleStyleSheet()
    style = ParagraphStyle("TableCell", parent=styles["BodyText"], fontSize=8.5, leading=10.5)
    return Paragraph(html_escape(str(value)), style)
