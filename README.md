# PulseIQ Africa

PulseIQ Africa is an AI-powered decision intelligence web app for small businesses and financial teams. It turns CSV records into dashboards, risk predictions, suspicious-activity checks, and automated PDF reports.

## Live Demo

Add your Streamlit Community Cloud or Hugging Face Spaces link here after deployment.

## Problem Statement

Many small businesses and institutions in developing economies keep useful data in Excel or messy CSV files, but they do not have a simple way to turn that data into decisions. PulseIQ Africa helps users understand performance, credit risk, and suspicious activity from spreadsheet data.

## Features

- Upload a CSV file or load the built-in demo dataset.
- Measure rows, columns, missing values, duplicate rows, and data quality score.
- View dashboard KPIs, revenue trends, repayment/default status, risk levels, transaction distribution, customer segments, and suspicious-activity categories.
- Train Logistic Regression, Random Forest, and Decision Tree models for default risk prediction.
- Display accuracy, precision, recall, F1-score, ROC-AUC, and confusion matrix-ready results.
- Score a single customer or loan application with a decision, reason, and suggested action.
- Detect anomalies with transparent business rules.
- Generate a downloadable PulseIQ Business Intelligence PDF report.
- Ask a rule-based insight assistant business questions without needing a paid AI API.

## Tech Stack

- Streamlit for the web app
- Python for application logic
- pandas and numpy for data handling
- Plotly for charts
- scikit-learn for machine learning
- ReportLab for PDF report generation

## Screenshots

Add screenshots from the running app after deployment:

- Home page
- Dashboard page
- Prediction page
- Anomaly Detection page
- Report page

## How the Model Works

PulseIQ normalizes uploaded CSV headers and builds a model frame from these fields when available:

- income
- loan_amount
- repayment_history_score
- existing_debt
- transaction_frequency
- account_age_months
- employment_status
- segment
- business_type
- region

If the dataset contains a `defaulted` column, PulseIQ uses it as the target. If it contains `repayment_status`, default-like labels are converted into the target. If neither exists, PulseIQ derives a starter target from repayment history, loan-to-income pressure, and existing debt pressure so the demo remains testable.

## Evaluation Metrics

The app trains three beginner-friendly classifiers and selects the strongest one by F1-score and ROC-AUC:

- Logistic Regression
- Random Forest
- Decision Tree

Displayed metrics:

- Accuracy
- Precision
- Recall
- F1-score
- ROC-AUC

## How to Run Locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/generate_demo_data.py
streamlit run app.py
```

## Deployment Notes

For Streamlit Community Cloud:

1. Push this project to GitHub.
2. Create a new Streamlit app from the repository.
3. Set the main file path to `app.py`.
4. Confirm that `requirements.txt` is detected.

For Hugging Face Spaces:

1. Create a new Space with the Streamlit SDK.
2. Upload this repository.
3. Keep `app.py` at the repository root.

## Future Improvements

- User login
- Real database
- Admin dashboard
- AI chatbot API
- Email report delivery
- More datasets
- Role-based access
- API endpoint for businesses

