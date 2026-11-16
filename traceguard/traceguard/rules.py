"""Rule engine. One function per rule -> (boolean mask, reason text). Thresholds are configurable examples,
not legal limits."""
import numpy as np
import pandas as pd

DEFAULT_CFG = {
    "large_amount": 10_000.0,
    "struct_threshold": 10_000.0,   # reporting threshold being avoided
    "struct_band": 0.10,            # "just below" = within 10% under the threshold
    "struct_min_count": 3,
    "struct_window_days": 3,
    "velocity_max_per_day": 10,
    "z_threshold": 3.0,
    "z_min_history": 5,
    "high_risk_countries": ["Iran", "North Korea", "Myanmar", "Syria", "Yemen", "Nigeria",
                            "Pakistan", "Mexico", "Morocco", "Turkey", "UAE", "Albania"],
    "weights": {"large": 30, "structuring": 40, "velocity": 20, "zscore": 20, "country": 30},
    "ml_weight": 0.3,        # share of ML score in the final risk score
    "ml_reason_min": 80,     # ML score at which "ML anomaly" is quoted as a reason
    "alert_threshold": 30,   # final risk score that raises an alert
}

RULE_DOCS = {
    "Large amount": "Large amount: a single transaction at or above the configured limit. Large transfers are "
                    "not illegal, but they deserve a check of source of funds and customer profile.",
    "Structuring": "Structuring (smurfing): several payments placed just under a reporting threshold within a short "
                   "window, usually to avoid triggering reports. Look for repeated near-threshold amounts.",
    "High velocity": "High velocity: a sender makes unusually many transactions in one day. Rapid movement of money "
                     "through an account is a common layering pattern.",
    "Statistical outlier": "Statistical outlier: the amount is far above the sender's own history (z-score above the "
                           "configured limit). It shows behaviour that does not match the account's normal pattern.",
    "High-risk country": "High-risk country: the sender or receiver is in a jurisdiction on the configured high-risk "
                         "list. Such transfers need enhanced due diligence.",
    "ML anomaly": "ML anomaly: the Isolation Forest model found the transaction unusual compared with the rest of "
                  "the data (amount, daily count, and the sender's average). It is combined with the rule score.",
    "risk score": "Risk score: weighted rule flags (0-100) are blended with the ML anomaly score. An alert is raised "
                  "when the final score reaches the alert threshold. All thresholds are adjustable examples.",
    "false positive": "False positives: alerts that turn out to be legitimate. Combining rules with an ML score "
                      "lowers them, because a single rule alone is not enough to raise an alert unless the "
                      "model also finds the transaction unusual.",
}


def _large(df, cfg):
    t = cfg["large_amount"]
    return df["amount"] >= t, "Large amount: " + df["amount"].map("{:,.2f}".format) + f" >= {t:,.0f}"


def _structuring(df, cfg):
    t = cfg["struct_threshold"]
    lo = t * (1 - cfg["struct_band"])
    near = df[(df["amount"] >= lo) & (df["amount"] < t)]
    mask = pd.Series(False, index=df.index)
    win = cfg["struct_window_days"] * 86400
    for _, g in near.sort_values("date").groupby("sender"):
        if len(g) < cfg["struct_min_count"]:
            continue
        ts = (g["date"] - pd.Timestamp("1970-01-01")).dt.total_seconds().values
        counts = np.arange(len(ts)) - np.searchsorted(ts, ts - win, side="left") + 1
        mask.loc[g.index[counts >= cfg["struct_min_count"]]] = True
    text = (f"Structuring: {cfg['struct_min_count']}+ payments between {lo:,.0f} and {t:,.0f} "
            f"within {cfg['struct_window_days']} days")
    return mask, pd.Series(text, index=df.index)


def _velocity(df, cfg):
    n = df.groupby(["sender", df["date"].dt.floor("D")])["amount"].transform("size")
    return n > cfg["velocity_max_per_day"], "High velocity: " + n.astype(str) + " transactions in one day"


def _zscore(df, cfg):
    g = df.groupby("sender")["amount"]
    mean, std, cnt = g.transform("mean"), g.transform("std"), g.transform("size")
    z = ((df["amount"] - mean) / std.where(std > 0)).fillna(0)
    mask = (cnt >= cfg["z_min_history"]) & (z > cfg["z_threshold"])
    return mask, "Statistical outlier: z-score " + z.round(1).astype(str) + " vs sender's history"


def _country(df, cfg):
    hr = {c.strip().lower() for c in cfg["high_risk_countries"] if c.strip()}
    mask = pd.Series(False, index=df.index)
    for col in ("sender_country", "receiver_country"):
        if col in df:
            mask |= df[col].astype(str).str.strip().str.lower().isin(hr)
    s = df.get("sender_country", pd.Series("?", index=df.index)).fillna("?").astype(str)
    r = df.get("receiver_country", pd.Series("?", index=df.index)).fillna("?").astype(str)
    return mask, "High-risk country: " + s + " -> " + r


RULES = [("large", _large), ("structuring", _structuring), ("velocity", _velocity),
         ("zscore", _zscore), ("country", _country)]


def apply_rules(df, cfg):
    """Adds rule_score (0-100) and reasons (text). Expects columns sender, amount, date (datetime)."""
    df = df.copy()
    score = pd.Series(0.0, index=df.index)
    reasons = pd.Series("", index=df.index)
    for key, fn in RULES:
        mask, text = fn(df, cfg)
        score += mask * cfg["weights"][key]
        reasons.loc[mask] = reasons.loc[mask] + text.loc[mask] + "; "
    df["rule_score"] = score.clip(upper=100)
    df["reasons"] = reasons
    return df
