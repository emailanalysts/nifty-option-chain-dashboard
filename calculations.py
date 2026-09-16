import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _db_url():
    return st.secrets["connections"]["postgresql"]["url"]


def _connect():
    import psycopg2
    return psycopg2.connect(_db_url(), connect_timeout=10)


def database_status():
    """Return a safe, non-secret Supabase connectivity summary for the UI."""
    try:
        with _connect() as con:
            with con.cursor() as cur:
                cur.execute("SELECT COUNT(*), MAX(snapshot_time) FROM option_chain_snapshots")
                count, latest = cur.fetchone()
        latest_text = None
        if latest is not None:
            latest_ts = pd.Timestamp(latest)
            if latest_ts.tzinfo is None:
                latest_ts = latest_ts.tz_localize("UTC")
            latest_text = latest_ts.tz_convert(IST).strftime("%d-%b-%Y %H:%M:%S IST")
        return {"connected": True, "count": int(count or 0), "latest": latest_text, "error": None}
    except Exception as e:
        return {"connected": False, "count": 0, "latest": None, "error": str(e)}


def prepare_chain(df, symbol):
    df = df.copy()
    df["expiryDate"] = pd.to_datetime(df["expiryDate"], dayfirst=True, errors="coerce")
    df["strikePrice"] = pd.to_numeric(df["strikePrice"], errors="coerce")
    numeric_cols = [
        "CE_OI", "CE_change_OI", "CE_volume", "CE_IV", "CE_Premium",
        "PE_OI", "PE_change_OI", "PE_volume", "PE_IV", "PE_Premium",
        "underlyingValue",
    ]
    for c in numeric_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df = df.sort_values("strikePrice").reset_index(drop=True)
    df["symbol"] = symbol
    return df


def atm_strike(df):
    spot = float(df["underlyingValue"].iloc[0])
    idx = (df["strikePrice"] - spot).abs().idxmin()
    return float(df.loc[idx, "strikePrice"])


def strike_wise_oi(df, window=10):
    atm = atm_strike(df)
    strikes = sorted(df["strikePrice"].unique())
    nearest = min(range(len(strikes)), key=lambda i: abs(strikes[i] - atm))
    lo = max(0, nearest - window)
    hi = min(len(strikes), nearest + window + 1)
    return df[df["strikePrice"].isin(strikes[lo:hi])][
        ["strikePrice", "CE_OI", "PE_OI"]
    ].sort_values("strikePrice")


def max_pain(df, return_table=False):
    strikes = np.sort(df["strikePrice"].unique())
    calls = df.groupby("strikePrice")["CE_OI"].sum()
    puts = df.groupby("strikePrice")["PE_OI"].sum()
    pain = []
    for settlement in strikes:
        call_pain = sum(max(0.0, settlement - k) * calls.get(k, 0) for k in strikes)
        put_pain = sum(max(0.0, k - settlement) * puts.get(k, 0) for k in strikes)
        pain.append((settlement, call_pain + put_pain))
    out = pd.DataFrame(pain, columns=["strikePrice", "totalPain"])
    mp = float(out.loc[out["totalPain"].idxmin(), "strikePrice"])
    return (mp, out) if return_table else mp


def overall_oi(nifty, bank):
    return {
        "NIFTY": {"CE": int(nifty["CE_OI"].sum()), "PE": int(nifty["PE_OI"].sum())},
        "BANKNIFTY": {"CE": int(bank["CE_OI"].sum()), "PE": int(bank["PE_OI"].sum())},
    }


def _read_df(sql, params):
    with _connect() as con:
        return pd.read_sql_query(sql, con, params=params)


def load_intraday_history(symbol, trading_date=None):
    date_value = pd.Timestamp(trading_date).date() if trading_date else datetime.now(IST).date()
    df = _read_df(
        """
        SELECT snapshot_time AS timestamp, symbol, expiry_date AS expiry,
               spot, cumulative_coi
        FROM option_chain_snapshots
        WHERE symbol=%s AND trading_date=%s
        ORDER BY snapshot_time
        """,
        (symbol, date_value),
    )
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(IST)
    return df


def latest_saved_trading_date(symbol):
    with _connect() as con:
        with con.cursor() as cur:
            cur.execute(
                "SELECT MAX(trading_date) FROM option_chain_snapshots WHERE symbol=%s",
                (symbol,),
            )
            row = cur.fetchone()
    return row[0].isoformat() if row and row[0] else None


def previous_saved_trading_date(symbol, before_date):
    before = pd.Timestamp(before_date).date()
    with _connect() as con:
        with con.cursor() as cur:
            cur.execute(
                "SELECT MAX(trading_date) FROM option_chain_snapshots WHERE symbol=%s AND trading_date < %s",
                (symbol, before),
            )
            row = cur.fetchone()
    return row[0].isoformat() if row and row[0] else None


def load_latest_snapshot_on_or_before(symbol, trading_date):
    if not trading_date:
        return pd.DataFrame()
    target = pd.Timestamp(trading_date).date()
    with _connect() as con:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT snapshot_time, expiry_date, chain_data
                FROM option_chain_snapshots
                WHERE symbol=%s AND trading_date <= %s
                ORDER BY snapshot_time DESC
                LIMIT 1
                """,
                (symbol, target),
            )
            row = cur.fetchone()
    if not row:
        return pd.DataFrame()
    _, expiry, chain_data = row
    records = chain_data or []
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["expiryDate"] = pd.Timestamp(expiry)
    df["symbol"] = symbol
    return prepare_chain(df, symbol)
