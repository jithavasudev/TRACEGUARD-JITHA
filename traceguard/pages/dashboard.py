import pandas as pd
import plotly.express as px
import streamlit as st
import db
from auth import require_login

require_login()
st.title("📊 Dashboard")

batches = db.query("SELECT id, filename, uploaded_at, row_count FROM upload_batch ORDER BY id DESC")
if batches.empty:
    st.info("No data yet. Upload a CSV first.")
    st.stop()

options = {"All batches": None}
options.update({f"#{r.id} · {r.filename} · {r.row_count:,} rows": int(r.id) for r in batches.itertuples()})
bid = options[st.selectbox("Batch", list(options))]
where, params = ("WHERE batch_id=?", (bid,)) if bid else ("", ())
df = db.query(f"SELECT id, sender, receiver, amount, tx_date, label, rule_score, ml_score, risk_score, "
              f"reasons, flagged FROM transactions {where}", params)
df["tx_date"] = pd.to_datetime(df["tx_date"])
fl = df[df["flagged"] == 1]
mules = fl["reasons"].str.extract(r"Mule pass-through: account (\S+)")[0].dropna().nunique()

k = st.columns(5)
k[0].metric("Total transactions", f"{len(df):,}")
k[1].metric("Flagged", f"{len(fl):,}", f"{len(fl) / max(len(df), 1):.2%} of total", delta_color="off")
k[2].metric("Flagged value", f"{fl['amount'].sum():,.0f}")
k[3].metric("Senders flagged", f"{fl['sender'].nunique():,}")
k[4].metric("Suspected mule accounts", f"{mules:,}")

c1, c2 = st.columns(2)
daily = df.groupby(df["tx_date"].dt.floor("D")).agg(total=("id", "size"), flagged=("flagged", "sum")).reset_index()
c1.plotly_chart(px.line(daily, x="tx_date", y=["total", "flagged"], title="Transactions over time",
                        labels={"tx_date": "Date", "value": "Count", "variable": ""}))
top = (fl.groupby("sender").agg(alerts=("id", "size"), avg_risk=("risk_score", "mean"))
       .sort_values(["alerts", "avg_risk"], ascending=False).head(10).reset_index())
if top.empty:
    c2.info("No flagged senders.")
else:
    c2.plotly_chart(px.bar(top, x="alerts", y="sender", color="avg_risk", orientation="h",
                           title="Top 10 risky senders", color_continuous_scale="Reds")
                    .update_yaxes(autorange="reversed", type="category"))

hits = fl["reasons"].fillna("").str.split("; ").explode().str.split(":").str[0].str.strip()
hits = hits[hits != ""].value_counts().reset_index()
hits.columns = ["rule", "count"]
if not hits.empty:
    st.plotly_chart(px.bar(hits, x="count", y="rule", orientation="h", title="Flagged transactions by rule")
                    .update_yaxes(autorange="reversed"))

if df["label"].notna().any():
    st.subheader("Detection quality on labelled data")
    lab = df.loc[df["label"].notna()]
    truth = lab["label"] == 1

    def stats(flag):
        tp, fp, fn = int((flag & truth).sum()), int((flag & ~truth).sum()), int((~flag & truth).sum())
        return {"alerts": tp + fp, "true positives": tp, "false positives": fp,
                "precision": tp / (tp + fp) if tp + fp else 0, "recall": tp / (tp + fn) if tp + fn else 0}

    res = pd.DataFrame({"Rules only (any rule fires)": stats(lab["rule_score"] > 0),
                        "Rules + ML (final score)": stats(lab["flagged"] == 1)}).T
    st.dataframe(res.style.format({"alerts": "{:.0f}", "true positives": "{:.0f}", "false positives": "{:.0f}",
                                "precision": "{:.1%}", "recall": "{:.1%}"}))
    fp_r, fp_c = res.iloc[0]["false positives"], res.iloc[1]["false positives"]
    if fp_r > 0:
        st.metric("False-positive reduction (rules + ML vs rules only)", f"{(fp_r - fp_c) / fp_r:.1%}")
else:
    st.caption("Tip: map a label column (e.g. Is_laundering) on upload to see precision, recall and FP reduction.")
