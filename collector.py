import json
import os
import sys
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg2
from psycopg2.extras import Json

from nse_data import fetch_option_chain
from calculations import prepare_chain

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)


def db_url():
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError("SUPABASE_DB_URL environment variable is not set")
    return url


def connect():
    return psycopg2.connect(db_url(), connect_timeout=15)


def save_snapshot(df):
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

    with connect() as con:
        with con.cursor() as cur:
            cur.execute(
                """
                SELECT cumulative_coi, chain_data
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
                previous_chain = prev[1] or []
                prev_ce = sum(float(x.get("CE_OI", 0)) for x in previous_chain)
                prev_pe = sum(float(x.get("PE_OI", 0)) for x in previous_chain)
                increment = (pe_oi - prev_pe) - (ce_oi - prev_ce)
                cumulative = float(prev[0] or 0) + increment

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

    return {
        "symbol": symbol,
        "snapshot_time": now.isoformat(),
        "trading_date": trading_date.isoformat(),
        "expiry": expiry.isoformat(),
        "spot": spot,
        "cumulative_coi": cumulative,
    }


def main():
    now = datetime.now(IST)
    print(f"IST time: {now:%Y-%m-%d %H:%M:%S %Z}")

    if now.weekday() >= 5:
        print("Weekend: collector skipped.")
        return 0

    if not (MARKET_OPEN <= now.time() <= MARKET_CLOSE):
        print("Outside 09:15–15:30 IST: collector skipped.")
        return 0

    results = []
    for symbol in ("NIFTY", "BANKNIFTY"):
        try:
            raw = fetch_option_chain(symbol)
            df = prepare_chain(raw, symbol)
            result = save_snapshot(df)
            results.append(result)
            print(
                f"Saved {symbol}: expiry={result['expiry']} "
                f"spot={result['spot']:.2f} cumulative_coi={result['cumulative_coi']:.2f}"
            )
        except Exception as exc:
            print(f"ERROR {symbol}: {exc}")
            return 1

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
