import json
import os
import sys
import time
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg2
from psycopg2.extras import Json

from nse_data import fetch_option_chain
from calculations import prepare_chain

# ============================================================
# SETTINGS
# ============================================================
IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
SYMBOLS = ("NIFTY", "BANKNIFTY")


def get_db_url():
    """Read the Supabase PostgreSQL URL from the GitHub Actions secret."""
    url = os.getenv("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError("Missing required environment variable: SUPABASE_DB_URL")
    return url


def market_is_open(now=None):
    now = now or datetime.now(IST)
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def _as_float(value, default=0.0):
    try:
        result = float(value)
        return result if pd.notna(result) else default
    except (TypeError, ValueError):
        return default


def save_snapshot(symbol, raw_df, snapshot_time=None):
    """Save one NIFTY/BANKNIFTY option-chain snapshot to Supabase."""
    if raw_df is None or raw_df.empty:
        raise RuntimeError(f"NSE returned an empty option chain for {symbol}")

    df = prepare_chain(raw_df, symbol)
    if df.empty:
        raise RuntimeError(f"Could not prepare option-chain rows for {symbol}")

    now = snapshot_time or datetime.now(IST)
    # Collector is scheduled every few minutes; keep at most one row per symbol/minute.
    now = now.replace(second=0, microsecond=0)
    trading_date = now.date()

    spot = _as_float(df["underlyingValue"].iloc[0])
    ce_oi = float(pd.to_numeric(df["CE_OI"], errors="coerce").fillna(0).sum())
    pe_oi = float(pd.to_numeric(df["PE_OI"], errors="coerce").fillna(0).sum())
    ce_change = float(pd.to_numeric(df["CE_change_OI"], errors="coerce").fillna(0).sum())
    pe_change = float(pd.to_numeric(df["PE_change_OI"], errors="coerce").fillna(0).sum())

    # Match the dashboard's COI convention: PE change in OI minus CE change in OI.
    coi_increment = pe_change - ce_change

    expiry = pd.to_datetime(df["expiryDate"], errors="coerce").dropna()
    expiry_date = expiry.iloc[0].date() if not expiry.empty else None
    if expiry_date is None:
        raise RuntimeError(f"Could not determine expiry date for {symbol}")

    # Store the normalized rows as JSON records, as expected by calculations.py.
    chain_records = json.loads(
        df.to_json(orient="records", date_format="iso", date_unit="ms")
    )

    db_url = get_db_url()
    with psycopg2.connect(db_url, connect_timeout=15) as con:
        with con.cursor() as cur:
            # Read the latest prior cumulative value for this trading day. Excluding
            # this minute makes reruns idempotent when the same-minute row is replaced.
            cur.execute(
                """
                SELECT cumulative_coi
                FROM option_chain_snapshots
                WHERE symbol = %s
                  AND trading_date = %s
                  AND snapshot_time < %s
                ORDER BY snapshot_time DESC
                LIMIT 1
                """,
                (symbol, trading_date, now),
            )
            previous = cur.fetchone()
            previous_cumulative = _as_float(previous[0]) if previous else 0.0
            cumulative_coi = previous_cumulative + coi_increment

            # Replace any existing snapshot for the same symbol and minute.
            cur.execute(
                """
                DELETE FROM option_chain_snapshots
                WHERE symbol = %s
                  AND snapshot_time >= %s
                  AND snapshot_time < %s
                """,
                (symbol, now, now + pd.Timedelta(minutes=1).to_pytimedelta()),
            )

            cur.execute(
                """
                INSERT INTO option_chain_snapshots
                    (snapshot_time, trading_date, symbol, expiry_date,
                     spot, cumulative_coi, chain_data)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    now,
                    trading_date,
                    symbol,
                    expiry_date,
                    spot,
                    cumulative_coi,
                    Json(chain_records),
                ),
            )

    print(
        f"Saved {symbol}: spot={spot:.2f}, CE OI={ce_oi:.0f}, "
        f"PE OI={pe_oi:.0f}, cumulative COI={cumulative_coi:.0f}, "
        f"expiry={expiry_date}, time={now.strftime('%Y-%m-%d %H:%M:%S IST')}"
    )


def main():
    now = datetime.now(IST)
    print(f"Collector started at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    if not market_is_open(now):
        print("Outside NSE market hours or weekend; skipping collection.")
        return

    errors = []
    for symbol in SYMBOLS:
        try:
            print(f"Fetching {symbol} option chain...")
            chain = fetch_option_chain(symbol)
            save_snapshot(symbol, chain, now)
        except Exception as exc:
            # Continue to the other symbol even if one fetch fails.
            message = f"{symbol} failed: {type(exc).__name__}: {exc}"
            errors.append(message)
            print(message, file=sys.stderr)
        time.sleep(1)

    if errors:
        raise RuntimeError("One or more symbols failed: " + " | ".join(errors))

    print("Collector completed successfully.")


if __name__ == "__main__":
    main()
