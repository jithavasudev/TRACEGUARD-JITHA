"""Rule engine. Each rule returns (boolean mask, reason text for the flagged rows).
Thresholds are configurable examples, not legal limits."""
import numpy as np
import pandas as pd

DEFAULT_CFG = {
    # classic AML
    "large_amount": 10_000.0,
    "struct_threshold": 10_000.0, "struct_band": 0.10, "struct_min_count": 3, "struct_window_days": 3,
    "velocity_max_per_day": 10,
    "z_threshold": 3.0, "z_min_history": 5,
    "high_risk_countries": ["Iran", "North Korea", "Myanmar", "Syria", "Yemen", "Nigeria",
                            "Pakistan", "Mexico", "Morocco", "Turkey", "UAE", "Albania"],
    # cyber-fraud / mule patterns
    "fanin_min_senders": 5,          # distinct senders paying one receiver in a day
    "fanout_min_receivers": 8,       # distinct receivers paid by one sender in a day
    "mule_min_senders": 3, "mule_min_in": 5_000.0, "mule_ratio": 0.8,   # forwarded / received
    "dormant_days": 60, "dormant_min_amount": 5_000.0,
    "shared_device_min": 3, "shared_ip_min": 5,
    "round_min_repeat": 3,
    "odd_hours_min_amount": 2_000.0,
    "weights": {"large": 30, "structuring": 40, "velocity": 20, "zscore": 20, "country": 30,
                "fanin": 25, "fanout": 20, "mule": 40, "dormant": 25, "device": 35, "ip": 20,
                "round": 15, "odd_hours": 10},
    "ml_weight": 0.3, "ml_reason_min": 80, "alert_threshold": 30,
}

RULE_DOCS = {
    "Large amount": "Large amount: a single transaction at or above the configured limit. Not illegal by itself, but worth a check of source of funds and customer profile.",
    "Structuring": "Structuring (smurfing): several payments just under a reporting threshold within a short window, usually to avoid triggering reports.",
    "High velocity": "High velocity: a sender makes unusually many transactions in one day. Rapid movement of money is a common layering pattern.",
    "Statistical outlier": "Statistical outlier: the amount is far above the sender's own history (z-score above the limit). It does not match the account's normal behaviour.",
    "High-risk country": "High-risk country: sender or receiver is in a jurisdiction on the configured high-risk list. Needs enhanced due diligence.",
    "Fan-in": "Fan-in: many different senders pay one receiver in a single day. This is typical of a collector or mule account receiving money from multiple fraud victims.",
    "Fan-out": "Fan-out: one sender pays many different receivers in a day. This is typical of a distributor account spreading money to hide the trail.",
    "Mule pass-through": "Mule pass-through: an account receives money from several senders and forwards almost all of it onwards. Mule accounts hold funds only briefly, so the balance returns to near zero.",
    "Dormant account active": "Dormant account activation: an account silent for a long time suddenly moves a large amount. Fraudsters often buy or take over old accounts.",
    "Shared device": "Shared device: one device is used by several different accounts. This is a strong sign that one operator controls those accounts (a mule ring).",
    "Shared IP": "Shared IP: many accounts transact from one IP address. It is weaker than a shared device because networks can be shared, so it carries less weight.",
    "Round amount": "Round amount: the same round amount is sent repeatedly. This often indicates scripted or manual transfers set up in advance.",
    "Odd hours": "Odd hours: a sizeable transaction at night. Alone it is weak, but it supports other signals such as rapid onward transfers.",
    "ML anomaly": "ML anomaly: the Isolation Forest model found this transaction unusual compared with the rest of the data. The alert names the feature that drove it.",
    "risk score": "Risk score: weighted rule flags (0-100) are blended with the ML anomaly score. An alert is raised at the alert threshold. All thresholds are adjustable examples.",
    "false positive": "False positives: alerts that turn out to be legitimate. Combining rules with an ML score lowers them, and analyst feedback shows which rules produce the most.",
    "network ring": "Network ring: a group of connected flagged accounts. Rings point to organised mule networks, so investigators work them as one case.",
}


def _empty(df):
    return pd.Series(False, index=df.index), pd.Series(dtype=object)


def _fmt(s, template):
    return s.map(template.format)


def _const(df, m, text):
    return pd.Series(text, index=df.index[m], dtype=object)


def _large(df, cfg):
    t = cfg["large_amount"]
    m = df["amount"] >= t
    return m, _fmt(df.loc[m, "amount"], f"Large amount: {{:,.2f}} >= {t:,.0f}")


def _structuring(df, cfg):
    t = cfg["struct_threshold"]
    lo = t * (1 - cfg["struct_band"])
    near = df[(df["amount"] >= lo) & (df["amount"] < t)]
    m = pd.Series(False, index=df.index)
    win = cfg["struct_window_days"] * 86400
    for _, g in near.sort_values("date").groupby("sender"):
        if len(g) < cfg["struct_min_count"]:
            continue
        ts = (g["date"] - pd.Timestamp("1970-01-01")).dt.total_seconds().values
        counts = np.arange(len(ts)) - np.searchsorted(ts, ts - win, side="left") + 1
        m.loc[g.index[counts >= cfg["struct_min_count"]]] = True
    return m, _const(df, m, f"Structuring: {cfg['struct_min_count']}+ payments between {lo:,.0f} and {t:,.0f} "
                            f"within {cfg['struct_window_days']} days")


def _velocity(df, cfg):
    n = df.groupby(["sender", df["date"].dt.floor("D")])["amount"].transform("size")
    m = n > cfg["velocity_max_per_day"]
    return m, _fmt(n[m], "High velocity: {} transactions in one day")


def _zscore(df, cfg):
    g = df.groupby("sender")["amount"]
    mean, std, cnt = g.transform("mean"), g.transform("std"), g.transform("size")
    z = ((df["amount"] - mean) / std.where(std > 0)).fillna(0)
    m = (cnt >= cfg["z_min_history"]) & (z > cfg["z_threshold"])
    return m, _fmt(z[m].round(1), "Statistical outlier: z-score {} vs sender's history")


def _country(df, cfg):
    hr = {c.strip().lower() for c in cfg["high_risk_countries"] if c.strip()}
    m = pd.Series(False, index=df.index)
    for col in ("sender_country", "receiver_country"):
        if col in df:
            m |= df[col].astype(str).str.strip().str.lower().isin(hr)
    sub = df.loc[m]
    s = sub["sender_country"].fillna("?").astype(str) if "sender_country" in sub else pd.Series("?", index=sub.index)
    r = sub["receiver_country"].fillna("?").astype(str) if "receiver_country" in sub else pd.Series("?", index=sub.index)
    return m, "High-risk country: " + s + " -> " + r


def _fanin(df, cfg):
    n = df.groupby(["receiver", df["date"].dt.floor("D")])["sender"].transform("nunique")
    m = n >= cfg["fanin_min_senders"]
    return m, _fmt(n[m], "Fan-in: {} different senders paid this receiver in one day")


def _fanout(df, cfg):
    n = df.groupby(["sender", df["date"].dt.floor("D")])["receiver"].transform("nunique")
    m = n >= cfg["fanout_min_receivers"]
    return m, _fmt(n[m], "Fan-out: sender paid {} different receivers in one day")


def _mule(df, cfg):
    inn = df.groupby("receiver").agg(total_in=("amount", "sum"), n_senders=("sender", "nunique"))
    out = df.groupby("sender")["amount"].sum().rename("total_out")
    acc = inn.join(out, how="inner")
    acc["ratio"] = acc["total_out"] / acc["total_in"]
    mules = acc[(acc["n_senders"] >= cfg["mule_min_senders"]) & (acc["total_in"] >= cfg["mule_min_in"])
                & (acc["ratio"] >= cfg["mule_ratio"])]
    if mules.empty:
        return _empty(df)
    d = mules.to_dict("index")
    is_s, is_r = df["sender"].isin(d), df["receiver"].isin(d)
    m = is_s | is_r
    acct = df["sender"].where(is_s, df["receiver"])[m]
    text = acct.map(lambda a: f"Mule pass-through: account {a} received {d[a]['total_in']:,.0f} from "
                              f"{int(d[a]['n_senders'])} senders and forwarded {d[a]['ratio']:.0%}")
    return m, text


def _dormant(df, cfg):
    gap = df.sort_values("date").groupby("sender")["date"].diff().dt.days.reindex(df.index)
    m = (gap >= cfg["dormant_days"]) & (df["amount"] >= cfg["dormant_min_amount"])
    return m, _fmt(gap[m].astype(int), "Dormant account active: {} days of silence, then a large payment")


def _shared(df, col, min_n, label):
    if col not in df:
        return _empty(df)
    v = df[col].astype(str).str.strip()
    v = v.where(df[col].notna() & ~v.str.lower().isin(["", "nan", "none"]))
    n = df["sender"].groupby(v).transform("nunique")
    m = n >= min_n
    return m, _fmt(n[m].astype(int), label + " used by {} different accounts")


def _device(df, cfg):
    return _shared(df, "device_id", cfg["shared_device_min"], "Shared device: device")


def _ip(df, cfg):
    return _shared(df, "ip", cfg["shared_ip_min"], "Shared IP: address")


def _round(df, cfg):
    cnt = df.groupby(["sender", "amount"])["amount"].transform("size")
    m = (df["amount"] % 1000 == 0) & (cnt >= cfg["round_min_repeat"])
    return m, _fmt(df.loc[m, "amount"], "Round amount: {:,.0f} sent repeatedly")


def _odd_hours(df, cfg):
    hr = df["date"].dt.hour
    if hr.nunique() <= 1:   # no real time-of-day in the data
        return _empty(df)
    m = (hr < 5) & (df["amount"] >= cfg["odd_hours_min_amount"])
    return m, _fmt(hr[m], "Odd hours: sizeable payment at {}:00 at night")


RULES = [("large", _large), ("structuring", _structuring), ("velocity", _velocity), ("zscore", _zscore),
         ("country", _country), ("fanin", _fanin), ("fanout", _fanout), ("mule", _mule),
         ("dormant", _dormant), ("device", _device), ("ip", _ip), ("round", _round),
         ("odd_hours", _odd_hours)]


def apply_rules(df, cfg):
    """Adds rule_score (0-100) and reasons. Expects columns sender, receiver, amount, date (datetime)."""
    df = df.copy()
    score = pd.Series(0.0, index=df.index)
    reasons = pd.Series("", index=df.index)
    for key, fn in RULES:
        mask, text = fn(df, cfg)
        if not mask.any():
            continue
        text = text.astype(str)
        score += mask.astype(float) * cfg["weights"][key]
        reasons.loc[mask] = reasons.loc[mask] + text + "; "
    df["rule_score"] = score.clip(upper=100)
    df["reasons"] = reasons
    return df
