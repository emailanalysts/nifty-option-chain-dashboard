"""
Read-only benchmark: NSE NIFTY option chain vs FYERS NIFTY and SENSEX option chains.

- Does NOT write to Supabase or modify dashboard files.
- Run during market hours for meaningful live-data comparison.
- Measures elapsed time and response payload sizes.
- NSE bytes are measured from actual HTTP response bodies (homepage + contract info + chain).
- FYERS byte size is an estimate of the returned decoded JSON payload, because the SDK
  does not expose raw HTTP response bytes.
- Uses three trials by default to keep request volume modest.
"""

import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:
    sys.exit("Missing dependency 'requests'. Install with: python -m pip install requests")

try:
    from fyers_apiv3 import fyersModel
except ImportError:
    fyersModel = None

IST = ZoneInfo("Asia/Kolkata")
TRIALS = 3
TIMEOUT = 20

NSE_HOME = "https://www.nseindia.com/option-chain"
NSE_API = "https://www.nseindia.com/api"
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.nseindia.com/option-chain",
    "X-Requested-With": "XMLHttpRequest",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
}

def now_ist():
    return datetime.now(IST).isoformat(timespec="seconds")

def is_market_hours():
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    open_time = now.replace(hour=9, minute=15, second=0, microsecond=0)
    close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_time <= now <= close_time

def record_result(rows, provider, instrument, trial, elapsed, payload_bytes,
                  status, rows_count="", note=""):
    rows.append({
        "timestamp_ist": now_ist(),
        "provider": provider,
        "instrument": instrument,
        "trial": trial,
        "elapsed_seconds": round(elapsed, 4) if elapsed is not None else "",
        "payload_bytes": payload_bytes if payload_bytes is not None else "",
        "payload_kb": round(payload_bytes / 1024, 3) if payload_bytes is not None else "",
        "http_or_api_status": status,
        "option_entries": rows_count,
        "note": note,
    })

def nse_fetch_once(symbol):
    """Measure all three NSE HTTP responses needed for one option-chain fetch."""
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    total_bytes = 0
    t0 = time.perf_counter()

    r_home = session.get(NSE_HOME, timeout=TIMEOUT)
    total_bytes += len(r_home.content)
    r_home.raise_for_status()

    r_info = session.get(
        f"{NSE_API}/option-chain-contract-info",
        params={"symbol": symbol},
        timeout=TIMEOUT,
    )
    total_bytes += len(r_info.content)
    r_info.raise_for_status()
    info = r_info.json()

    expiries = info.get("expiryDates") or info.get("records", {}).get("expiryDates")
    if not expiries:
        raise RuntimeError(f"NSE did not return expiryDates; response keys={list(info.keys())}")

    # Existing project uses nearest expiry; keep same selection behavior.
    import pandas as pd
    parsed = pd.to_datetime(expiries, dayfirst=True, errors="coerce")
    valid = [(d, e) for d, e in zip(parsed, expiries) if not pd.isna(d)]
    if not valid:
        raise RuntimeError(f"Could not parse NSE expiries: {expiries[:5]}")
    expiry = min(valid, key=lambda item: item[0])[1]

    r_chain = session.get(
        f"{NSE_API}/option-chain-v3",
        params={"type": "Indices", "symbol": symbol, "expiry": expiry},
        timeout=TIMEOUT,
    )
    total_bytes += len(r_chain.content)
    r_chain.raise_for_status()
    payload = r_chain.json()
    elapsed = time.perf_counter() - t0

    candidates = []
    if isinstance(payload.get("filtered"), dict):
        candidates = payload["filtered"].get("data") or []
    if not candidates and isinstance(payload.get("records"), dict):
        candidates = payload["records"].get("data") or []
    if not candidates:
        candidates = payload.get("data") or []

    if not candidates:
        raise RuntimeError(f"NSE returned no option rows; response keys={list(payload.keys())}")

    return elapsed, total_bytes, len(candidates), f"expiry={expiry}; HTTP 200"

def fyers_fetch_once(client, symbol):
    """Measure FYERS optionchain call; response size is serialized JSON estimate."""
    request = {
        "symbol": symbol,
        "strikecount": 10,
        "timestamp": "",
        "greeks": "1",
    }
    t0 = time.perf_counter()
    response = client.optionchain(data=request)
    elapsed = time.perf_counter() - t0

    if not isinstance(response, dict):
        raise RuntimeError(f"Unexpected FYERS response type: {type(response).__name__}")

    payload_bytes = len(json.dumps(response, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    status = f"{response.get('s', 'unknown')} / {response.get('code', '')}"
    if response.get("s") != "ok":
        raise RuntimeError(f"FYERS API error: status={status}; message={response.get('message', 'no message')}")

    data = response.get("data") or {}
    entries = data.get("optionsChain") or []
    expiry_count = len(data.get("expiryData") or [])
    return elapsed, payload_bytes, len(entries), f"{status}; expiry_count={expiry_count}; serialized response size estimate"

def summarize(rows):
    print("\n" + "=" * 76)
    print("BENCHMARK SUMMARY")
    print("=" * 76)
    keys = sorted({(r["provider"], r["instrument"]) for r in rows})
    for provider, instrument in keys:
        ok = [
            r for r in rows
            if r["provider"] == provider and r["instrument"] == instrument
            and isinstance(r["elapsed_seconds"], (int, float))
        ]
        if not ok:
            print(f"{provider:8} {instrument:20} No successful trials")
            continue
        times = [r["elapsed_seconds"] for r in ok]
        sizes = [r["payload_bytes"] for r in ok if isinstance(r["payload_bytes"], int)]
        entries = [r["option_entries"] for r in ok if isinstance(r["option_entries"], int)]
        print(f"{provider:8} {instrument:20} "
              f"success={len(ok)}/{TRIALS} "
              f"avg_time={statistics.mean(times):.3f}s "
              f"median_time={statistics.median(times):.3f}s "
              f"avg_payload={statistics.mean(sizes)/1024:.2f} KB "
              f"avg_entries={statistics.mean(entries) if entries else 'n/a'}")
    print("\nNote: NSE payload includes homepage + expiry lookup + option-chain HTTP bodies.")
    print("FYERS payload is serialized response JSON size, not exact wire/network usage.")
    print("Compare only successful trials; NSE and FYERS may return different strike ranges.")

def main():
    print("READ-ONLY OPTION-CHAIN BENCHMARK")
    print("Time (IST):", now_ist())
    print("No Supabase writes; no dashboard changes.")
    if not is_market_hours():
        print("WARNING: Outside weekday market hours (09:15–15:30 IST).")
        print("You can continue, but latency/data availability may not represent live trading.")
        answer = input("Continue anyway? Type YES to continue: ").strip()
        if answer != "YES":
            print("Cancelled. Run this script during market hours.")
            return

    app_id = os.getenv("FYERS_APP_ID")
    token_path = Path(os.getenv("FYERS_TOKEN_FILE", "fyers_access_token.txt"))
    token = token_path.read_text(encoding="utf-8").strip() if token_path.exists() else ""
    if not app_id or not token:
        print("\nFYERS credentials not found.")
        print("Set FYERS_APP_ID in this PowerShell terminal and ensure the token file exists.")
        print("Default token file: fyers_access_token.txt")
        sys.exit(2)
    if fyersModel is None:
        print("Missing FYERS SDK. Install in your active venv: python -m pip install fyers-apiv3")
        sys.exit(2)

    fyers = fyersModel.FyersModel(
        client_id=app_id,
        token=token,
        is_async=False,
        log_path="",
    )

    rows = []
    tests = [
        ("NSE", "NIFTY", lambda: nse_fetch_once("NIFTY")),
        ("FYERS", "NIFTY", lambda: fyers_fetch_once(fyers, "NSE:NIFTY50-INDEX")),
        ("FYERS", "SENSEX", lambda: fyers_fetch_once(fyers, "BSE:SENSEX-INDEX")),
    ]

    print(f"\nRunning {TRIALS} trial(s) per source. Please avoid running multiple copies.")
    for provider, instrument, fetch in tests:
        for trial in range(1, TRIALS + 1):
            print(f"\n[{provider} {instrument}] trial {trial}/{TRIALS} ...", flush=True)
            try:
                elapsed, size, count, note = fetch()
                record_result(rows, provider, instrument, trial, elapsed, size, "OK", count, note)
                print(f"OK | time={elapsed:.3f}s | payload={size/1024:.2f} KB | entries={count}")
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                record_result(rows, provider, instrument, trial, None, None, "ERROR", "", message)
                print("FAILED |", message)
            # Small pause to avoid firing requests back-to-back.
            time.sleep(1.5)

    stamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
    csv_path = Path(f"optionchain_benchmark_{stamp}_IST.csv")
    json_path = Path(f"optionchain_benchmark_{stamp}_IST.json")
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nDetailed CSV saved: {csv_path.resolve()}")
        print(f"Detailed JSON saved: {json_path.resolve()}")
    summarize(rows)
    print("\nShare the summary and CSV rows (do not share any tokens or secrets).")

if __name__ == "__main__":
    main()
