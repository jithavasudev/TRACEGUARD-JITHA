"""Isolation Forest anomaly score (0-100) with a named driver for explainability."""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

DRIVER_NAMES = {
    "log_amount": "amount size", "tx_per_day": "daily transaction count", "log_sender_avg": "sender's average amount",
    "ratio_to_avg": "amount vs sender's average", "sender_tx_count": "sender activity",
    "sender_unique_receivers": "number of receivers", "receiver_unique_senders": "number of senders paying the receiver",
}


def build_features(df):
    day = df["date"].dt.floor("D")
    g = df.groupby("sender")["amount"]
    avg = g.transform("mean")
    return pd.DataFrame({
        "log_amount": np.log1p(df["amount"]),
        "tx_per_day": df.groupby(["sender", day])["amount"].transform("size"),
        "log_sender_avg": np.log1p(avg),
        "ratio_to_avg": (df["amount"] / avg.where(avg > 0)).fillna(1.0),
        "sender_tx_count": g.transform("size"),
        "sender_unique_receivers": df.groupby("sender")["receiver"].transform("nunique"),
        "receiver_unique_senders": df.groupby("receiver")["sender"].transform("nunique"),
    }, index=df.index)


def add_ml_score(df, cfg=None, max_train=100_000):
    df = df.copy()
    df["ml_driver"] = ""
    if len(df) < 20:
        df["ml_score"] = 0.0
        return df
    X = build_features(df)
    model = IsolationForest(n_estimators=150, contamination="auto", random_state=42, n_jobs=-1)
    model.fit(X.sample(min(len(X), max_train), random_state=42))
    raw = -model.score_samples(X)  # higher = more anomalous
    lo, hi = raw.min(), raw.max()
    df["ml_score"] = ((raw - lo) / (hi - lo) * 100).round(1) if hi > lo else 0.0
    thr = (cfg or {}).get("ml_reason_min", 80)
    high = (df["ml_score"] >= thr).values
    if high.any():  # which feature is most unusual for these rows?
        med = X.median()
        mad = (X - med).abs().median()
        scale = mad.where(mad > 0, X.std()).replace(0, 1).fillna(1)
        z = ((X[high] - med) / scale).abs()
        df.loc[high, "ml_driver"] = z.idxmax(axis=1).map(DRIVER_NAMES).values
    return df
