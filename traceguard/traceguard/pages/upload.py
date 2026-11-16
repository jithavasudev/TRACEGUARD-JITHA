import pandas as pd
import streamlit as st
import db, pipeline, rules
from auth import require_login

user = require_login()
st.title("📤 Upload & Analyse")

ALIASES = {
    "sender": ["sender_account", "sender", "nameorig", "orig_account", "sender_id", "from", "source"],
    "receiver": ["receiver_account", "receiver", "namedest", "dest_account", "receiver_id", "to", "target"],
    "amount": ["amount", "tx_amount", "transaction_amount", "value"],
    "date": ["date", "timestamp", "tran_timestamp", "time_stamp", "datetime", "step"],
    "time": ["time"],
    "sender_country": ["sender_bank_location", "sender_country", "origin_country"],
    "receiver_country": ["receiver_bank_location", "receiver_country", "destination_country"],
    "label": ["is_laundering", "is_sar", "isfraud", "label", "is_fraud"],
}
REQUIRED = ["sender", "receiver", "amount", "date"]


def guess(field, cols):
    low = {c.lower(): c for c in cols}
    for a in ALIASES[field]:
        if a in low:
            return low[a]
    return None


# ----- settings -----
cfg = {**rules.DEFAULT_CFG, "weights": dict(rules.DEFAULT_CFG["weights"])}
with st.expander("⚙️ Thresholds (configurable examples, not legal limits)"):
    c1, c2, c3 = st.columns(3)
    cfg["large_amount"] = c1.number_input("Large amount ≥", value=cfg["large_amount"], step=500.0)
    cfg["struct_threshold"] = c1.number_input("Structuring threshold", value=cfg["struct_threshold"], step=500.0)
    cfg["struct_min_count"] = c2.number_input("Structuring: min payments", value=cfg["struct_min_count"], min_value=2)
    cfg["struct_window_days"] = c2.number_input("Structuring window (days)", value=cfg["struct_window_days"], min_value=1)
    cfg["velocity_max_per_day"] = c3.number_input("Max tx per sender per day", value=cfg["velocity_max_per_day"], min_value=1)
    cfg["z_threshold"] = c3.number_input("Z-score threshold", value=cfg["z_threshold"], step=0.5)
    cfg["ml_weight"] = c1.slider("ML weight in risk score", 0.0, 1.0, cfg["ml_weight"], 0.05)
    cfg["alert_threshold"] = c2.slider("Alert threshold (0-100)", 0, 100, cfg["alert_threshold"])
    countries = st.text_area("High-risk countries (comma-separated)", ", ".join(cfg["high_risk_countries"]))
    cfg["high_risk_countries"] = [c.strip() for c in countries.split(",") if c.strip()]

file = st.file_uploader("Upload a transactions CSV", type=["csv"])
max_rows = st.number_input("Max rows to load (use a sample for big files)", 1000, 1_000_000, 200_000, 10_000)

if file is None:
    st.info("Works with SAML-D, IBM AMLSim, IBM AML or PaySim-style CSVs. You map the columns next.")
    st.stop()

try:
    raw = pd.read_csv(file, nrows=int(max_rows))
except Exception as e:
    st.error(f"Could not read this file as CSV: {e}")
    st.stop()
if raw.empty:
    st.error("The file has no rows.")
    st.stop()

st.write(f"Loaded **{len(raw):,}** rows, **{raw.shape[1]}** columns.")
st.dataframe(raw.head(5))

st.subheader("Map columns")
cols = list(raw.columns)
mapping, c = {}, st.columns(4)
for i, f in enumerate(REQUIRED + ["time", "sender_country", "receiver_country", "label"]):
    g = guess(f, cols)
    opts = ([] if f in REQUIRED else ["(none)"]) + cols
    idx = opts.index(g) if g in opts else 0
    sel = c[i % 4].selectbox(f"{f}{' *' if f in REQUIRED else ''}", opts, index=idx, key=f"map_{f}")
    mapping[f] = None if sel == "(none)" else sel

if st.button("Run analysis", type="primary"):
    used = [v for k, v in mapping.items() if v and k in REQUIRED]
    if len(set(used)) < len(used):
        st.error("Each required field must use a different column.")
        st.stop()
    with st.spinner("Cleaning data, running rules and ML model..."):
        df = pd.DataFrame({
            "sender": raw[mapping["sender"]].astype(str).str.strip(),
            "receiver": raw[mapping["receiver"]].astype(str).str.strip(),
            "amount": pd.to_numeric(raw[mapping["amount"]], errors="coerce"),
        })
        d = raw[mapping["date"]].astype(str)
        if mapping["time"]:
            d = d + " " + raw[mapping["time"]].astype(str)
        df["date"] = pd.to_datetime(d, errors="coerce")
        for f in ("sender_country", "receiver_country"):
            if mapping[f]:
                df[f] = raw[mapping[f]].astype(str).str.strip()
        df["label"] = pd.to_numeric(raw[mapping["label"]], errors="coerce") if mapping["label"] else float("nan")

        before = len(df)
        df = df.dropna(subset=["amount", "date"])
        df = df[(df["amount"] > 0) & (df["sender"] != "") & (df["sender"] != "nan")]
        dropped = before - len(df)
        if df.empty:
            st.error("No valid rows after cleaning. Check that the amount and date columns are mapped correctly.")
            st.stop()
        df = df.reset_index(drop=True)
        for f in ("sender_country", "receiver_country"):
            if f not in df:
                df[f] = None
        df["tx_date"] = df["date"].dt.strftime("%Y-%m-%d %H:%M:%S")
        df = pipeline.analyse(df, cfg)
        batch_id = db.save_batch(df, file.name, user["username"])

    st.success(f"Batch #{batch_id} saved. Dropped {dropped:,} invalid rows.")
    k = st.columns(4)
    k[0].metric("Transactions", f"{len(df):,}")
    k[1].metric("Alerts raised", f"{int(df['flagged'].sum()):,}")
    k[2].metric("Flagged value", f"{df.loc[df['flagged'] == 1, 'amount'].sum():,.0f}")
    k[3].metric("Rule hits (any rule)", f"{int((df['rule_score'] > 0).sum()):,}")
    st.dataframe(df[df["flagged"] == 1].sort_values("risk_score", ascending=False)
                 [["sender", "receiver", "amount", "tx_date", "risk_score", "reasons"]].head(100))
    st.caption("Open Dashboard or Alerts from the sidebar to explore the results.")
