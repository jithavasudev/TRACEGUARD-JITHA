"""Rules + ML -> final risk score, flag and explainable reasons."""
import rules, ml_model


def analyse(df, cfg):
    df = rules.apply_rules(df, cfg)
    df = ml_model.add_ml_score(df, cfg)
    w = cfg["ml_weight"]
    df["risk_score"] = ((1 - w) * df["rule_score"] + w * df["ml_score"]).round(1)
    hi = df["ml_score"] >= cfg["ml_reason_min"]
    df.loc[hi, "reasons"] = df.loc[hi, "reasons"] + "ML anomaly: unusual pattern (score " + \
        df.loc[hi, "ml_score"].astype(str) + "); "
    df["reasons"] = df["reasons"].str.rstrip("; ")
    df["flagged"] = (df["risk_score"] >= cfg["alert_threshold"]).astype(int)
    return df
