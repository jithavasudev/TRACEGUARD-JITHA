import pandas as pd
import streamlit as st
import db, ingest, pipeline, rules
from auth import require_login

user = require_login()
st.title("📤 Upload & Analyse")

cfg = {**rules.DEFAULT_CFG, "weights": dict(rules.DEFAULT_CFG["weights"])}
with st.expander("⚙️ Classic AML thresholds (configurable examples, not legal limits)"):
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
with st.expander("🕵️ Cyber-fraud / mule rule settings"):
    c1, c2, c3 = st.columns(3)
    cfg["fanin_min_senders"] = c1.number_input("Fan-in: senders per receiver per day ≥", value=cfg["fanin_min_senders"], min_value=2)
    cfg["fanout_min_receivers"] = c1.number_input("Fan-out: receivers per sender per day ≥", value=cfg["fanout_min_receivers"], min_value=2)
    cfg["mule_min_senders"] = c2.number_input("Mule: min distinct senders", value=cfg["mule_min_senders"], min_value=2)
    cfg["mule_min_in"] = c2.number_input("Mule: min money received", value=cfg["mule_min_in"], step=500.0)
    cfg["mule_ratio"] = c2.slider("Mule: share forwarded onward", 0.5, 1.0, cfg["mule_ratio"], 0.05)
    cfg["dormant_days"] = c3.number_input("Dormant after (days)", value=cfg["dormant_days"], min_value=7)
    cfg["dormant_min_amount"] = c3.number_input("Dormant: min amount", value=cfg["dormant_min_amount"], step=500.0)
    cfg["shared_device_min"] = c1.number_input("Shared device: accounts ≥", value=cfg["shared_device_min"], min_value=2)
    cfg["shared_ip_min"] = c2.number_input("Shared IP: accounts ≥", value=cfg["shared_ip_min"], min_value=2)
    cfg["round_min_repeat"] = c3.number_input("Round amount: repeats ≥", value=cfg["round_min_repeat"], min_value=2)

file = st.file_uploader("Upload a transactions CSV", type=["csv"])
max_rows = st.number_input("Max rows to load (use a sample for big files)", 1000, 1_000_000, 200_000, 10_000)
if file is None:
    st.info("Works with SAML-D, IBM AMLSim, IBM AML or PaySim-style CSVs. Device, IP and channel columns are optional "
            "but enable the shared-device and shared-IP rules.")
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
for i, f in enumerate(ingest.FIELDS):
    g = ingest.guess(f, cols)
    opts = ([] if f in ingest.REQUIRED else ["(none)"]) + cols
    sel = c[i % 4].selectbox(f"{f}{' *' if f in ingest.REQUIRED else ''}", opts,
                             index=opts.index(g) if g in opts else 0, key=f"map_{f}")
    mapping[f] = None if sel == "(none)" else sel

if st.button("Run analysis", type="primary"):
    used = [mapping[k] for k in ingest.REQUIRED]
    if len(set(used)) < len(used):
        st.error("Each required field must use a different column.")
        st.stop()
    with st.spinner("Cleaning data, running rules and ML model..."):
        df, dropped = ingest.clean(raw, mapping)
        if df.empty:
            st.error("No valid rows after cleaning. Check that amount and date are mapped correctly.")
            st.stop()
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
    st.caption("Next: open **Network & Trace** to see rings of connected accounts, or **Alerts** to review.")
