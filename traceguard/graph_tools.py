"""Network analysis: rings (connected flagged accounts), cycles, hubs, and trace-the-money."""
from itertools import islice
import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import db


def flagged_edges(batch_id=None):
    where, p = ("AND batch_id=?", (batch_id,)) if batch_id else ("", ())
    return db.query(f"""SELECT sender, receiver, COUNT(*) n, SUM(amount) amount, MAX(risk_score) max_risk
                        FROM transactions WHERE flagged=1 {where} GROUP BY sender, receiver""", p)


def build_graph(edges):
    G = nx.DiGraph()
    for r in edges.itertuples():
        G.add_edge(r.sender, r.receiver, n=int(r.n), amount=float(r.amount), risk=float(r.max_risk))
    for node in G.nodes:
        risks = [d["risk"] for _, _, d in G.in_edges(node, data=True)] + \
                [d["risk"] for _, _, d in G.out_edges(node, data=True)]
        G.nodes[node]["risk"] = max(risks) if risks else 0
    return G


def find_rings(G, min_size=3):
    """Weakly-connected groups of flagged accounts, biggest money first."""
    rings = []
    for comp in nx.weakly_connected_components(G):
        if len(comp) < min_size:
            continue
        sub = G.subgraph(comp)
        cent = nx.degree_centrality(sub)
        hubs = sorted(cent, key=cent.get, reverse=True)[:3]
        try:
            cycles = list(islice(nx.simple_cycles(sub, length_bound=4), 20))
        except Exception:
            cycles = []
        rings.append({"accounts": len(comp), "links": sub.number_of_edges(),
                      "total_amount": round(sum(d["amount"] for _, _, d in sub.edges(data=True))),
                      "max_risk": max(d["risk"] for _, _, d in sub.edges(data=True)),
                      "hubs": ", ".join(hubs), "cycles": len(cycles), "nodes": sorted(comp), "cycle_list": cycles})
    rings.sort(key=lambda r: r["total_amount"], reverse=True)
    for i, r in enumerate(rings, 1):
        r["ring"] = i
    return rings


def trace(account, direction="forward", depth=3, batch_id=None, max_rows_per_hop=2000):
    """Follow money out of (forward) or into (backward) an account, hop by hop, using SQL."""
    a, b = ("sender", "receiver") if direction == "forward" else ("receiver", "sender")
    frontier, seen, frames = {account}, {account}, []
    for hop in range(1, depth + 1):
        if not frontier:
            break
        parts = []
        nodes = list(frontier)
        for i in range(0, len(nodes), 500):
            chunk = nodes[i:i + 500]
            ph = ",".join("?" * len(chunk))
            extra, p = ("AND batch_id=?", [batch_id]) if batch_id else ("", [])
            parts.append(db.query(f"""SELECT id, sender, receiver, amount, tx_date, risk_score FROM transactions
                                      WHERE {a} IN ({ph}) {extra} ORDER BY amount DESC LIMIT {max_rows_per_hop}""",
                                  (*chunk, *p)))
        df = pd.concat(parts, ignore_index=True)
        if df.empty:
            break
        df["hop"] = hop
        frames.append(df)
        frontier = set(df[b]) - seen
        seen |= frontier
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def plot_graph(G, title="", highlight=None, max_nodes=150):
    if G.number_of_nodes() > max_nodes:
        keep = sorted(G.degree, key=lambda x: x[1], reverse=True)[:max_nodes]
        G = G.subgraph([n for n, _ in keep])
    pos = nx.spring_layout(G, seed=42)
    ex, ey = [], []
    for u, v in G.edges:
        ex += [pos[u][0], pos[v][0], None]
        ey += [pos[u][1], pos[v][1], None]
    fig = go.Figure(go.Scatter(x=ex, y=ey, mode="lines", line=dict(width=0.8, color="#999"), hoverinfo="none"))
    if G.number_of_edges() <= 80:   # arrows show direction of money
        for u, v in G.edges:
            fig.add_annotation(x=pos[v][0], y=pos[v][1], ax=pos[u][0], ay=pos[u][1], xref="x", yref="y",
                               axref="x", ayref="y", showarrow=True, arrowhead=3, arrowsize=1.1,
                               arrowwidth=0.8, arrowcolor="#888", standoff=8)
    nodes = list(G.nodes)
    hl = set(highlight or [])
    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in nodes], y=[pos[n][1] for n in nodes], mode="markers+text" if len(nodes) <= 30 else "markers",
        text=[str(n) for n in nodes], textposition="top center",
        marker=dict(size=[min(10 + 3 * G.degree(n), 40) for n in nodes],
                    color=[G.nodes[n].get("risk", 0) for n in nodes], colorscale="Reds", cmin=0, cmax=100,
                    showscale=True, colorbar=dict(title="risk"),
                    line=dict(width=[3 if n in hl else 0.5 for n in nodes], color="black")),
        hovertext=[f"{n}<br>in: {G.in_degree(n)} · out: {G.out_degree(n)}<br>risk: {G.nodes[n].get('risk', 0):.0f}"
                   for n in nodes], hoverinfo="text"))
    fig.update_layout(title=title, showlegend=False, height=560, margin=dict(l=10, r=10, t=40, b=10),
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig
