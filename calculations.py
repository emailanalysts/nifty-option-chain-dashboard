import json
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import psycopg2
from psycopg2.extras import Json

IST = ZoneInfo("Asia/Kolkata")


def _db_url():
    return st.secrets["connections"]["postgresql"]["url"]


def _connect():
    return psycopg2.connect(_db_url(), connect_timeout=10)


def database_status():
    """Return a safe, non-secret Supabase connectivity summary for the UI."""
    try:
        with _connect() as con:
            with con.cursor() as cur:
                cur.execute("SELECT COUNT(*), MAX(snapshot_time) FROM option_chain_snapshots")
                count, latest = cur.fetchone()
        if latest is not None:
            latest_ist = pd.Timestamp(latest)
            if latest_ist.tzinfo is None:
                latest_ist = latest_ist.tz_localize("UTC")
            latest_text = latest_ist.tz_convert(IST).strftime("%d-%b-%Y %H:%M:%S IST")
        else:
            latest_text = None
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
        "underlyingValue"
    ]
    for c in numeric_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    today = pd.Timestamp.now(tz=IST).tz_localize(None).normalize()
    future = df.loc[df["expiryDate"] >= today, "expiryDate"]
    expiry = future.min() if not future.empty else df["expiryDate"].max()
    df = df[df["expiryDate"] == expiry].copy().sort_values("strikePrice").reset_index(drop=True)
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
    return df[df["strikePrice"].isin(strikes[max(0, nearest-window):min(len(strikes), nearest+window+1)])][
        ["strikePrice", "CE_OI", "PE_OI"]
    ].sort_values("strikePrice")


def max_pain(df, return_table=False):
    strikes = np.sort(df["strikePrice"].unique())
    calls = df.groupby("strikePrice")["CE_OI"].sum()
    puts = df.groupby("strikePrice")["PE_OI"].sum()
    pain = []
    for settlement in strikes:
        call_pain = sum(max(0.0, settlement-k) * calls.get(k, 0) for k in strikes)
        put_pain = sum(max(0.0, k-settlement) * puts.get(k, 0) for k in strikes)
        pain.append((settlement, call_pain + put_pain))
    out = pd.DataFrame(pain, columns=["strikePrice", "totalPain"])
    mp = float(out.loc[out["totalPain"].idxmin(), "strikePrice"])
    return (mp, out) if return_table else mp


def overall_oi(nifty, bank):
    return {
        "NIFTY": {"CE": int(nifty["CE_OI"].sum()), "PE": int(nifty["PE_OI"].sum())},
        "BANKNIFTY": {"CE": int(bank["CE_OI"].sum()), "PE": int(bank["PE_OI"].sum())},
    }


def current_coi(df):
    return float(df["PE_change_OI"].sum() - df["CE_change_OI"].sum())


def save_snapshot(df):
    """Save one complete chain snapshot and maintain a fresh daily cumulative COI."""
    symbol = str(df["symbol"].iloc[0])
    expiry = pd.Timestamp(df["expiryDate"].iloc[0]).date()
    spot = float(df["underlyingValue"].iloc[0])
    ce_oi = float(df["CE_OI"].sum())
    pe_oi = float(df["PE_OI"].sum())
    now = datetime.now(IST).replace(second=0, microsecond=0)
    trading_date = now.date()

    chain_records = []
    for _, r in df.iterrows():
        chain_records.append({
            "strikePrice": float(r["strikePrice"]),
            "CE_OI": float(r["CE_OI"]),
            "CE_change_OI": float(r["CE_change_OI"]),
            "CE_volume": float(r["CE_volume"]),
            "CE_IV": float(r["CE_IV"]),
            "CE_Premium": float(r["CE_Premium"]),
            "PE_OI": float(r["PE_OI"]),
            "PE_change_OI": float(r["PE_change_OI"]),
            "PE_volume": float(r["PE_volume"]),
            "PE_IV": float(r["PE_IV"]),
            "PE_Premium": float(r["PE_Premium"]),
            "underlyingValue": float(r["underlyingValue"]),
        })

    with _connect() as con:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT spot, cumulative_coi, chain_data
                FROM option_chain_snapshots
                WHERE symbol=%s AND expiry_date=%s AND trading_date=%s
                ORDER BY snapshot_time DESC
                LIMIT 1
                """,
                (symbol, expiry, trading_date),
            )
            prev = cur.fetchone()

            if prev is None:
                cumulative = 0.0
            else:
                previous_chain = prev[2] or []
                prev_ce = sum(float(x.get("CE_OI", 0)) for x in previous_chain)
                prev_pe = sum(float(x.get("PE_OI", 0)) for x in previous_chain)
                increment = (pe_oi - prev_pe) - (ce_oi - prev_ce)
                cumulative = float(prev[1] or 0) + increment

            cur.execute(
                """
                DELETE FROM option_chain_snapshots
                WHERE symbol=%s AND trading_date=%s AND expiry_date=%s AND snapshot_time=%s
                """,
                (symbol, trading_date, expiry, now),
            )
            cur.execute(
                """
                INSERT INTO option_chain_snapshots
                    (snapshot_time, trading_date, symbol, expiry_date, spot, cumulative_coi, chain_data)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (now, trading_date, symbol, expiry, spot, cumulative, Json(chain_records)),
            )
        con.commit()


def load_intraday_history(symbol, trading_date=None):
    date_value = pd.Timestamp(trading_date).date() if trading_date else datetime.now(IST).date()
    with _connect() as con:
        df = pd.read_sql_query(
            """
            SELECT snapshot_time AS timestamp, symbol, expiry_date AS expiry,
                   spot, cumulative_coi
            FROM option_chain_snapshots
            WHERE symbol=%s AND trading_date=%s
            ORDER BY snapshot_time
            """,
            con,
            params=(symbol, date_value),
        )
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(IST)
    return df


def latest_saved_trading_date(symbol):
    with _connect() as con:
        with con.cursor() as cur:
            cur.execute("SELECT MAX(trading_date) FROM option_chain_snapshots WHERE symbol=%s", (symbol,))
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

    snapshot_time, expiry, chain_data = row
    records = chain_data or []
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["expiryDate"] = pd.Timestamp(expiry)
    df["symbol"] = symbol
    return df.sort_values("strikePrice").reset_index(drop=True)


def load_coi_history_for_latest_day(symbol, on_or_before=None):
    date_str = on_or_before or latest_saved_trading_date(symbol)
    if not date_str:
        return pd.DataFrame()
    return load_intraday_history(symbol, date_str)
