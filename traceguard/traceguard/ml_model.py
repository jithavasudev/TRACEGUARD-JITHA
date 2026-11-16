"""Isolation Forest anomaly score (0-100)."""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


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
    }, index=df.index)


def add_ml_score(df, cfg=None, max_train=100_000):
    df = df.copy()
    if len(df) < 20:
        df["ml_score"] = 0.0
        return df
    X = build_features(df)
    train = X.sample(min(len(X), max_train), random_state=42)
    model = IsolationForest(n_estimators=150, contamination="auto", random_state=42, n_jobs=-1).fit(train)
    raw = -model.score_samples(X)  # higher = more anomalous
    lo, hi = raw.min(), raw.max()
    df["ml_score"] = ((raw - lo) / (hi - lo) * 100).round(1) if hi > lo else 0.0
    return df
