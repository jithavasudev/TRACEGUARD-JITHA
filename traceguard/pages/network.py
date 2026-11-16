import pandas as pd
import streamlit as st
import case_tools, db, graph_tools
from auth import require_login

user = require_login()
st.title("🕸️ Network & Trace the Money")

batches = db.query("SELECT id, filename, row_count FROM upload_batch ORDER BY id DESC")
if batches.empty:
    st.info("Upload data first.")
    st.stop()
options = {"All batches": None} | {f"#{r.id} · {r.filename}": int(r.id) for r in batches.itertuples()}
bid = options[st.selectbox("Batch", list(options))]

tab1, tab2 = st.tabs(["Rings of connected accounts", "Trace the money"])

with tab1:
    st.caption("Accounts linked by flagged transfers form rings. Rings point to organised mule networks, so they are "
               "worked as one case. Darker nodes carry higher risk; bigger nodes have more links.")
    edges = graph_tools.flagged_edges(bid)
    if edges.empty:
        st.info("No flagged transfers to build a network from.")
    else:
        G = graph_tools.build_graph(edges)
        min_size = st.slider("Minimum accounts in a ring", 2, 20, 3)
        rings = graph_tools.find_rings(G, min_size)
        if not rings:
            st.info("No rings of that size.")
        else:
            tbl = pd.DataFrame([{k: r[k] for k in ("ring", "accounts", "links", "total_amount", "max_risk", "hubs", "cycles")}
                                for r in rings])
            st.dataframe(tbl, hide_index=True)
            rid = st.selectbox("Inspect ring", [r["ring"] for r in rings])
            ring = next(r for r in rings if r["ring"] == rid)
            sub = G.subgraph(ring["nodes"])
            st.plotly_chart(graph_tools.plot_graph(sub, f"Ring {rid}: {ring['accounts']} accounts, "
                                                        f"{ring['total_amount']:,} moved", highlight=ring["hubs"].split(", ")))
            st.markdown(f"**Hub accounts (most connected):** {ring['hubs']}")
            if ring["cycles"]:
                st.warning(f"{ring['cycles']} circular flow(s) found (money returning to its source), for example: "
                           + " → ".join(map(str, ring["cycle_list"][0] + [ring["cycle_list"][0][0]])))
            if st.button("Create a case from this ring"):
                al = db.query("""SELECT a.id AS alert_id, t.sender, t.receiver FROM alert a
                                 JOIN transactions t ON t.id=a.tx_id""" + (" WHERE a.batch_id=?" if bid else ""),
                              (bid,) if bid else ())
                nodes = set(ring["nodes"])
                ids = al[al["sender"].isin(nodes) & al["receiver"].isin(nodes)]["alert_id"].tolist()
                cid = case_tools.create_case(f"Ring {rid}: hub {ring['hubs'].split(', ')[0]} "
                                             f"({ring['accounts']} accounts)", ids, user["username"])
                st.success(f"Created case #{cid} with {len(ids)} alerts. Open it under **Cases**.")

with tab2:
    st.caption("Follow money forward (where did it go?) or backward (where did it come from?) hop by hop.")
    c1, c2, c3 = st.columns([2, 1, 1])
    acct = c1.text_input("Account ID")
    direction = c2.radio("Direction", ["forward", "backward"], horizontal=True)
    depth = c3.slider("Hops", 1, 5, 3)
    if acct.strip():
        t = graph_tools.trace(acct.strip(), direction, depth, bid)
        if t.empty:
            st.warning("No transactions found for that account in this direction.")
        else:
            reached = set(t["receiver"] if direction == "forward" else t["sender"]) - {acct.strip()}
            m = st.columns(3)
            m[0].metric("Transfers followed", f"{len(t):,}")
            m[1].metric("Accounts reached", f"{len(reached):,}")
            m[2].metric("Total amount moved", f"{t['amount'].sum():,.0f}")
            e = t.groupby(["sender", "receiver"]).agg(n=("id", "size"), amount=("amount", "sum"),
                                                      max_risk=("risk_score", "max")).reset_index()
            st.plotly_chart(graph_tools.plot_graph(graph_tools.build_graph(e), f"{direction.title()} trace from {acct}",
                                                   highlight=[acct.strip()]))
            st.dataframe(t.sort_values(["hop", "amount"], ascending=[True, False]), hide_index=True)
            sig = (acct.strip(), direction, depth)
            if st.session_state.get("last_trace") != sig:   # log once per distinct trace, not on every rerun
                st.session_state["last_trace"] = sig
                db.log(user["username"], "trace", f"{direction} {acct.strip()} depth {depth}")
