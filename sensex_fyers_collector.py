"""Collect SENSEX option-chain and front-month futures snapshots via FYERS v3.

Required environment variables:
  FYERS_APP_ID, FYERS_ACCESS_TOKEN, SUPABASE_DB_URL
The FYERS access token is short-lived and must be refreshed according to FYERS auth rules.
"""
import os
import sys
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg2
from fyers_apiv3 import fyersModel

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
UNDERLYING = "BSE:SENSEX-INDEX"


def env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def client():
    return fyersModel.FyersModel(
        client_id=env("FYERS_APP_ID"),
        token=env("FYERS_ACCESS_TOKEN"),
        is_async=False,
        log_path="",
    )


def connect_db():
    return psycopg2.connect(env("SUPABASE_DB_URL"), connect_timeout=15, sslmode="require")


def market_is_open(now=None):
    now = now or datetime.now(IST)
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def number(value, default=None):
    try:
        result = float(value)
        return result if pd.notna(result) else default
    except (TypeError, ValueError):
        return default


def fetch_optionchain(api):
    response = api.optionchain(data={
        "symbol": UNDERLYING,
        "strikecount": 50,
        "timestamp": "",
        "greeks": "0",
    })
    if not isinstance(response, dict) or response.get("s") != "ok":
        raise RuntimeError(f"FYERS option-chain request failed: {response}")
    data = response.get("data") or {}
    entries = data.get("optionsChain") or []
    if not entries:
        raise RuntimeError("FYERS returned an empty SENSEX option chain")
    index_rows = [r for r in entries if not r.get("option_type") and number(r.get("ltp")) is not None]
    if not index_rows:
        raise RuntimeError("SENSEX index LTP was not present in option-chain response")
    spot = number(index_rows[0].get("ltp"))
    calls = [r for r in entries if r.get("option_type") == "CE"]
    puts = [r for r in entries if r.get("option_type") == "PE"]
    ce_oi = sum(number(r.get("oi"), 0) or 0 for r in calls)
    pe_oi = sum(number(r.get("oi"), 0) or 0 for r in puts)
    ce_change = sum(number(r.get("oich"), 0) or 0 for r in calls)
    pe_change = sum(number(r.get("oich"), 0) or 0 for r in puts)
    expiry = None
    expiry_data = data.get("expiryData") or []
    if expiry_data:
        # FYERS optionchain defaults to the nearest expiry. Save the first expiry date if available.
        expiry_text = expiry_data[0].get("date")
        expiry = pd.to_datetime(expiry_text, dayfirst=True, errors="coerce")
        expiry = expiry.date() if not pd.isna(expiry) else None
    return {
        "spot": spot,
        "ce_oi": float(ce_oi),
        "pe_oi": float(pe_oi),
        "oi_increment": float(pe_change - ce_change),
        "expiry_date": expiry,
        "chain_data": entries,
    }


def fetch_front_future(api):
    response = api.futureschain(data={"symbol": UNDERLYING})
    if not isinstance(response, dict) or response.get("s") != "ok":
        raise RuntimeError(f"FYERS futures-chain request failed: {response}")
    contracts = response.get("data") or []
    today = datetime.now(IST).date()
    candidates = []
    for item in contracts:
        symbol = item.get("symbol")
        if not symbol or symbol == UNDERLYING or not symbol.endswith("FUT"):
            continue
        expiry_raw = item.get("expiry") or item.get("expiryDate") or item.get("date")
        expiry = pd.NaT
        if expiry_raw not in (None, ""):
            # Futures-chain responses can represent expiry as epoch seconds or a date string.
            try:
                raw_num = float(expiry_raw)
                if raw_num > 100_000_000:
                    expiry = pd.to_datetime(raw_num, unit="s", errors="coerce")
            except (TypeError, ValueError):
                pass
            if pd.isna(expiry):
                expiry = pd.to_datetime(expiry_raw, dayfirst=True, errors="coerce")
        if pd.isna(expiry) or expiry.date() < today:
            continue
        candidates.append((expiry.date(), symbol, item))
    if not candidates:
        symbols = [x.get("symbol") for x in contracts if isinstance(x, dict)]
        raise RuntimeError(f"No unexpired SENSEX futures contract found. FYERS returned: {symbols}")
    expiry_date, symbol, chain_item = sorted(candidates, key=lambda x: x[0])[0]
    quote_response = api.quotes(data={"symbols": symbol})
    if not isinstance(quote_response, dict) or quote_response.get("s") != "ok":
        raise RuntimeError(f"FYERS futures quote request failed for {symbol}: {quote_response}")
    quote = next((x.get("v", {}) for x in quote_response.get("d", []) if x.get("s") == "ok"), {})
    price = number(quote.get("lp"), number(chain_item.get("ltp")))
    volume = number(quote.get("volume"))
    if price is None:
        raise RuntimeError(f"No last traded price returned for SENSEX future {symbol}")
    return {"symbol": symbol, "expiry_date": expiry_date, "price": float(price),
            "volume": int(volume) if volume is not None else None}


def save_option_snapshot(record, now):
    with connect_db() as con, con.cursor() as cur:
        cur.execute("""
            SELECT cumulative_coi FROM sensex_option_snapshots
            WHERE trading_date=%s AND snapshot_time < %s
            ORDER BY snapshot_time DESC LIMIT 1
        """, (now.date(), now))
        previous = cur.fetchone()
        cumulative = float(previous[0] or 0) if previous else 0.0
        cumulative += record["oi_increment"]
        cur.execute("""
            INSERT INTO sensex_option_snapshots
                (snapshot_time, trading_date, spot, expiry_date, cumulative_coi,
                 ce_oi, pe_oi, oi_increment, chain_data)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT (snapshot_time) DO UPDATE SET
                trading_date=EXCLUDED.trading_date, spot=EXCLUDED.spot,
                expiry_date=EXCLUDED.expiry_date, cumulative_coi=EXCLUDED.cumulative_coi,
                ce_oi=EXCLUDED.ce_oi, pe_oi=EXCLUDED.pe_oi,
                oi_increment=EXCLUDED.oi_increment, chain_data=EXCLUDED.chain_data
        """, (now, now.date(), record["spot"], record["expiry_date"], cumulative,
              record["ce_oi"], record["pe_oi"], record["oi_increment"],
              __import__("json").dumps(record["chain_data"])))
        con.commit()
    print(f"SENSEX option snapshot saved: spot={record['spot']:.2f}, CE OI={record['ce_oi']:.0f}, PE OI={record['pe_oi']:.0f}")


def save_futures_snapshot(record, now):
    volume = record["volume"]
    with connect_db() as con, con.cursor() as cur:
        cur.execute("""
            SELECT price, cumulative_volume, vwap FROM sensex_futures_snapshots
            WHERE trading_date=%s ORDER BY snapshot_time DESC LIMIT 1
        """, (now.date(),))
        previous = cur.fetchone()
        if previous is None or volume is None:
            vwap = record["price"]
        else:
            previous_price, previous_volume, previous_vwap = previous
            previous_volume = int(previous_volume or 0)
            if volume <= previous_volume:
                vwap = record["price"]
            else:
                interval_volume = volume - previous_volume
                prior_vwap = float(previous_vwap if previous_vwap is not None else previous_price or record["price"])
                vwap = (prior_vwap * previous_volume + record["price"] * interval_volume) / volume
        cur.execute("""
            INSERT INTO sensex_futures_snapshots
                (snapshot_time, trading_date, contract_symbol, expiry_date,
                 price, volume, cumulative_volume, vwap)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (snapshot_time) DO UPDATE SET
                trading_date=EXCLUDED.trading_date, contract_symbol=EXCLUDED.contract_symbol,
                expiry_date=EXCLUDED.expiry_date, price=EXCLUDED.price,
                volume=EXCLUDED.volume, cumulative_volume=EXCLUDED.cumulative_volume,
                vwap=EXCLUDED.vwap
        """, (now, now.date(), record["symbol"], record["expiry_date"], record["price"],
              volume, volume, float(vwap)))
        con.commit()
    print(f"SENSEX futures saved: {record['symbol']} price={record['price']:.2f}, volume={volume}, VWAP={vwap:.2f}")


def main():
    now = datetime.now(IST).replace(second=0, microsecond=0)
    print(f"SENSEX collector at {now.isoformat()}")
    if not market_is_open(now):
        print("Outside market hours or weekend; skipping.")
        return
    api = client()
    option_record = fetch_optionchain(api)
    future_record = fetch_front_future(api)
    save_option_snapshot(option_record, now)
    save_futures_snapshot(future_record, now)
    print("SENSEX collector completed.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
