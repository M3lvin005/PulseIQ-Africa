# PulseIQ Africa

**Decision-intelligence web app for small businesses and financial teams.** Upload a CSV of business records and get back dashboards, credit-default risk predictions, suspicious-activity flags, and a downloadable PDF report.



## The problem

Small businesses and lending institutions in developing economies keep useful data in Excel and messy CSV files, but have no simple way to turn that data into decisions. Commercial BI and credit-scoring tools are priced for enterprises. PulseIQ closes that gap: it takes a spreadsheet as-is and returns performance, risk, and anomaly analysis without configuration.

## What it does

**Data quality assessment** — Reports row and column counts, missing values, duplicate rows, and an overall data-quality score before any analysis runs.

**Dashboards** — Revenue trends, repayment and default status, risk-level breakdowns, transaction distribution, customer segments, and suspicious-activity categories.

**Credit risk prediction** — Trains three classifiers and selects the strongest by F1-score and ROC-AUC. Scores individual customers or loan applications with a decision, a reason, and a suggested action.

**Anomaly detection** — Flags suspicious transactions using transparent, inspectable business rules rather than a black-box model, so a reviewer can always see why something was flagged.

**Reporting** — Generates a downloadable PDF business-intelligence report via ReportLab.

**Insight assistant** — Answers plain-language questions about the dataset using rule-based logic, with no paid AI API required.

## Tech stack

| Layer | Choice |
|---|---|
| Web app | Streamlit |
| Language | Python |
| Data | pandas, NumPy |
| Charts | Plotly |
| ML | scikit-learn |
| PDF | ReportLab |

## How the model works

PulseIQ normalises uploaded CSV headers and assembles a model frame from these fields when present: `income`, `loan_amount`, `repayment_history_score`, `existing_debt`, `transaction_frequency`, `account_age_months`, `employment_status`, `segment`, `business_type`, `region`.

Target selection follows a fallback chain:

1. If the dataset has a `defaulted` column, that is the target.
2. If it has `repayment_status`, default-like labels are converted into the target.
3. If neither exists, a starter target is derived from repayment history, loan-to-income pressure, and existing-debt pressure so the demo remains testable.

**On the derived target:** step 3 exists so the app is explorable without a labelled dataset. Metrics produced under a derived target measure how well the model recovers the derivation rule, not real-world default risk. Treat them as a smoke test, not evidence of predictive power. Bring your own labelled data for meaningful evaluation.

## Models and metrics

Three classifiers are trained and compared:

- Logistic Regression
- Random Forest
- Decision Tree

Reported for each: accuracy, precision, recall, F1-score, ROC-AUC, and confusion-matrix-ready output.

## Running locally

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate_demo_data.py
streamlit run app.py
```

The app opens at `http://localhost:8501`. Use the built-in demo dataset if you do not have a CSV to hand.

## Deploying

**Streamlit Community Cloud** — Push to GitHub, create a new app from the repo, set the main file path to `app.py`, and confirm `requirements.txt` is detected.

**Hugging Face Spaces** — Create a Space with the Streamlit SDK, upload the repo, and keep `app.py` at the root.

## Expected CSV format

Column names are matched loosely, so `Loan Amount`, `loan_amount`, and `LOAN_AMOUNT` all resolve to the same field. No column is strictly required — the app adapts to what it finds and reports which fields it used.

| Column | Type | Notes |
|---|---|---|
| `income` | numeric | Monthly or annual, used consistently |
| `loan_amount` | numeric | Principal |
| `repayment_history_score` | numeric | Higher is better |
| `existing_debt` | numeric | Outstanding balance |
| `transaction_frequency` | numeric | Transactions per period |
| `account_age_months` | numeric | Account tenure |
| `employment_status` | categorical | |
| `segment` | categorical | |
| `defaulted` | binary | Target, if available |

## Limitations

- Trained on modest datasets; not calibrated for production lending decisions.
- Anomaly detection is rule-based, so it catches known patterns rather than novel fraud.
- No authentication or persistence — sessions are stateless and data is not stored.
- Single-user by design; not built for concurrent load.

## Roadmap

User login · persistent database · admin dashboard · LLM-backed chat assistant · scheduled email reports · role-based access · public API endpoint

## Author

Jomilojuoluwa Melvin Salami — [GitHub](https://github.com/M3lvin005) · [LinkedIn](https://linkedin.com/in/jomilojuoluwa-salami-493209227)
