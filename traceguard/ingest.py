"""Column mapping and cleaning for uploaded CSVs."""
import pandas as pd

ALIASES = {
    "sender": ["sender_account", "sender", "nameorig", "orig_account", "sender_id", "from", "source"],
    "receiver": ["receiver_account", "receiver", "namedest", "dest_account", "receiver_id", "to", "target"],
    "amount": ["amount", "tx_amount", "transaction_amount", "value"],
    "date": ["date", "timestamp", "tran_timestamp", "time_stamp", "datetime", "step"],
    "time": ["time"],
    "sender_country": ["sender_bank_location", "sender_country", "origin_country"],
    "receiver_country": ["receiver_bank_location", "receiver_country", "destination_country"],
    "device_id": ["device_id", "device", "deviceid", "device_hash"],
    "ip": ["ip", "ip_address", "ip_addr"],
    "channel": ["payment_type", "channel", "type", "tx_type"],
    "label": ["is_laundering", "is_sar", "isfraud", "label", "is_fraud"],
}
REQUIRED = ["sender", "receiver", "amount", "date"]
FIELDS = REQUIRED + ["time", "sender_country", "receiver_country", "device_id", "ip", "channel", "label"]


def guess(field, cols):
    low = {c.lower(): c for c in cols}
    for a in ALIASES[field]:
        if a in low:
            return low[a]
    return None


def clean(raw, mapping):
    """mapping: field -> column name or None. Returns (clean dataframe, number of dropped rows)."""
    df = pd.DataFrame({
        "sender": raw[mapping["sender"]].astype(str).str.strip(),
        "receiver": raw[mapping["receiver"]].astype(str).str.strip(),
        "amount": pd.to_numeric(raw[mapping["amount"]], errors="coerce"),
    })
    d = raw[mapping["date"]].astype(str)
    if mapping.get("time"):
        d = d + " " + raw[mapping["time"]].astype(str)
    df["date"] = pd.to_datetime(d, errors="coerce")
    for f in ("sender_country", "receiver_country", "device_id", "ip", "channel"):
        df[f] = raw[mapping[f]].astype(str).str.strip() if mapping.get(f) else None
    df["label"] = pd.to_numeric(raw[mapping["label"]], errors="coerce") if mapping.get("label") else float("nan")
    before = len(df)
    df = df.dropna(subset=["amount", "date"])
    df = df[(df["amount"] > 0) & (~df["sender"].isin(["", "nan"]))].reset_index(drop=True)
    df["tx_date"] = df["date"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df, before - len(df)
