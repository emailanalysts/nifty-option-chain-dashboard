from pathlib import Path
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

DB = Path(__file__).with_name("option_chain_history.db")
IST = ZoneInfo("Asia/Kolkata")

def prepare_chain(df, symbol):
    df = df.copy()

    df["expiryDate"] = pd.to_datetime(df["expiryDate"], dayfirst=True, errors="coerce")
    df["strikePrice"] = pd.to_numeric(df["strikePrice"], errors="coerce")

    numeric_cols = [
        "CE_OI", "CE_change_OI", "CE_volume", "CE_IV",
        "PE_OI", "PE_change_OI", "PE_volume", "PE_IV",
        "underlyingValue",
    ]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    today = pd.Timestamp.now(tz=IST).tz_localize(None).normalize()
    future = df.loc[df["expiryDate"] >= today, "expiryDate"]

    if future.empty:
        expiry = df["expiryDate"].max()
    else:
        expiry = future.min()

    df = df[df["expiryDate"] == expiry].copy()
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
        call_pain = sum(
            max(0.0, settlement - k) * calls.get(k, 0)
            for k in strikes
        )
        put_pain = sum(
            max(0.0, k - settlement) * puts.get(k, 0)
            for k in strikes
        )
        pain.append((settlement, call_pain + put_pain))

    out = pd.DataFrame(pain, columns=["strikePrice", "totalPain"])
    mp = float(out.loc[out["totalPain"].idxmin(), "strikePrice"])

    if return_table:
        return mp, out
    return mp

def overall_oi(nifty, bank):
    return {
        "NIFTY": {
            "CE": int(nifty["CE_OI"].sum()),
            "PE": int(nifty["PE_OI"].sum()),
        },
        "BANKNIFTY": {
            "CE": int(bank["CE_OI"].sum()),
            "PE": int(bank["PE_OI"].sum()),
        },
    }

def current_coi(df):
    # Net COI direction follows the workbook logic:
    # Put-side OI flow minus Call-side OI flow.
    return float(df["PE_change_OI"].sum() - df["CE_change_OI"].sum())

def _init_db():
    with sqlite3.connect(DB) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                expiry TEXT NOT NULL,
                spot REAL,
                ce_oi REAL,
                pe_oi REAL,
                coi_increment REAL,
                cumulative_coi REAL
            )
        """)
        con.commit()

def save_snapshot(df):
    _init_db()

    symbol = str(df["symbol"].iloc[0])
    expiry = str(df["expiryDate"].iloc[0].date())
    spot = float(df["underlyingValue"].iloc[0])
    ce_oi = float(df["CE_OI"].sum())
    pe_oi = float(df["PE_OI"].sum())

    now = datetime.now(IST).replace(second=0, microsecond=0)

    with sqlite3.connect(DB) as con:
        # Start a completely new intraday dataframe/COI series every day.
        # Never use the previous trading day's snapshot as the baseline.
        today = now.date().isoformat()

        prev = pd.read_sql_query(
            """
            SELECT ce_oi, pe_oi, cumulative_coi
            FROM snapshots
            WHERE symbol = ?
              AND expiry = ?
              AND substr(timestamp, 1, 10) = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            con,
            params=(symbol, expiry, today),
        )

        if prev.empty:
            increment = 0.0
            cumulative = 0.0
        else:
            ce_delta = ce_oi - float(prev.iloc[0]["ce_oi"])
            pe_delta = pe_oi - float(prev.iloc[0]["pe_oi"])
            increment = pe_delta - ce_delta
            cumulative = float(prev.iloc[0]["cumulative_coi"]) + increment

        con.execute(
            """
            INSERT INTO snapshots
            (timestamp, symbol, expiry, spot, ce_oi, pe_oi,
             coi_increment, cumulative_coi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now.isoformat(),
                symbol,
                expiry,
                spot,
                ce_oi,
                pe_oi,
                increment,
                cumulative,
            ),
        )
        con.commit()

def load_intraday_history(symbol):
    _init_db()

    today = datetime.now(IST).date().isoformat()

    with sqlite3.connect(DB) as con:
        df = pd.read_sql_query(
            """
            SELECT timestamp, symbol, expiry, spot,
                   ce_oi, pe_oi, coi_increment, cumulative_coi
            FROM snapshots
            WHERE symbol = ? AND substr(timestamp, 1, 10) = ?
            ORDER BY timestamp
            """,
            con,
            params=(symbol, today),
        )

    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df
