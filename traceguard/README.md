# TraceGuard: Cyber-Financial-Crime Monitoring System

TraceGuard reads bank transaction CSV files, flags suspicious activity with 13 rules plus an
Isolation Forest model, shows connected accounts as a network, and helps investigators manage
cases and export tamper-evident evidence. Built with Python and Streamlit.

## Features
- Login with roles (Analyst, Admin), hashed passwords, lockout, forced first-login password change
- CSV upload with automatic column mapping and cleaning
- 13 detection rules (large amount, structuring, velocity, outlier, high-risk country, fan-in,
  fan-out, mule pass-through, dormant account, shared device, shared IP, round amounts, odd hours)
- Isolation Forest anomaly score blended with the rule score into a 0-100 risk score
- Dashboard, alert review, account search, network rings, trace-the-money
- Cases, freeze-request list, evidence ZIP with SHA-256 hashes, audit log, admin reports

## Run it
```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```
Open http://localhost:8501 and log in with **admin / admin123**. You will be asked to set a new password.

## Try it with sample data
Go to **Upload & Analyse** and upload `sample_data/dummy_cyber_transactions.csv`
(synthetic data with planted mule-ring, structuring, fan-out, dormant-account and shared-device patterns).

## Project structure
| Path | Purpose |
|---|---|
| `app.py` | Login, forced password change, role-based menu |
| `db.py` | SQLite layer, password hashing, lockout, audit log |
| `rules.py`, `ml_model.py`, `pipeline.py` | Rules, Isolation Forest, risk score |
| `ingest.py` | Column mapping and cleaning |
| `graph_tools.py`, `case_tools.py` | Network analysis; cases and evidence |
| `pages/` | The 11 Streamlit pages |
| `sample_data/` | Synthetic test CSV |

Thresholds are configurable examples, not legal limits. Test data is synthetic.
