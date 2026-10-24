"""Collect MCX commodity option chains using the same browser session as the site.

Required environment variable: SUPABASE_DB_URL (PostgreSQL connection string).
Run on a 10-minute GitHub Actions schedule during the commodity session.
"""
import json, os, sys, time
from datetime import datetime, date
from zoneinfo import ZoneInfo
import psycopg2
from playwright.sync_api import sync_playwright

IST = ZoneInfo("Asia/Kolkata")
BASE = "https://www.mcxindia.com"
LANDING = BASE + "/market-data/option-chain"
COMMODITIES = {"GOLD":"GOLD", "SILVER":"SILVER", "CRUDEOIL":"CRUDEOIL", "NATURALGAS":"NATURALGAS"}


def fetch_chain(page, symbol):
    # Load the official page first so ASP.NET session and request-verification
    # state are created by the site itself. Select the commodity and a valid
    # expiry from the page controls, then fetch the same-origin JSON endpoint.
    page.goto(LANDING, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)

    selects = page.locator("select")
    select_count = selects.count()
    commodity_index = None
    for i in range(select_count):
        options = selects.nth(i).locator("option")
        for j in range(options.count()):
            opt = options.nth(j)
            value = (opt.get_attribute("value") or "").strip().upper()
            label = (opt.inner_text() or "").strip().upper()
            if value == symbol or label == symbol:
                commodity_index = i
                break
        if commodity_index is not None:
            break
    if commodity_index is None:
        raise RuntimeError(f"Could not find {symbol} in MCX commodity dropdowns ({select_count} select elements found)")

    commodity_select = selects.nth(commodity_index)
    chosen = None
    options = commodity_select.locator("option")
    for j in range(options.count()):
        opt = options.nth(j)
        value = (opt.get_attribute("value") or "").strip()
        label = (opt.inner_text() or "").strip().upper()
        if value.upper() == symbol or label == symbol:
            chosen = value
            break
    if chosen is None:
        raise RuntimeError(f"No selectable value found for {symbol}")
    commodity_select.select_option(value=chosen)
    page.wait_for_timeout(500)

    # Expiry dropdown is typically the next select after commodity. Prefer a
    # dropdown whose options resemble expiry dates; choose its first real option.
    expiry_value = None
    for i in range(selects.count()):
        if i == commodity_index:
            continue
        opts = selects.nth(i).locator("option")
        candidates = []
        for j in range(opts.count()):
            opt = opts.nth(j)
            value = (opt.get_attribute("value") or "").strip()
            label = (opt.inner_text() or "").strip()
            low = (value + " " + label).lower()
            if value and value.lower() not in ("0", "-1", "select", "") and any(mon in low for mon in ("jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec")):
                candidates.append(value)
        if candidates:
            expiry_value = candidates[0]
            selects.nth(i).select_option(value=expiry_value)
            break
    if not expiry_value:
        raise RuntimeError(f"Could not identify an expiry option for {symbol}; inspect MCX dropdowns")

    # Click Show to let the official UI initialize its request parameters.
    show = page.get_by_role("button", name="Show")
    if show.count():
        show.first.click(timeout=10000)
        page.wait_for_timeout(700)

    url = f"{BASE}/GetOptionChain?InstrumentType=optfut&Symbol={symbol}&Expiry={expiry_value}"
    result = page.evaluate("""async (url) => {
      const r = await fetch(url, {method:'GET', credentials:'include', headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json, text/javascript, */*; q=0.01'}});
      const text = await r.text();
      return {status:r.status, url:r.url, text:text};
    }""", url)
    if result["status"] != 200:
        raise RuntimeError(f"MCX {symbol} expiry={expiry_value}: HTTP {result['status']}; response={result['text'][:200]}")
    try:
        payload = json.loads(result["text"])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"MCX {symbol}: endpoint did not return JSON: {result['text'][:200]}") from e
    rows = payload.get("Data") or payload.get("data") or []
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"MCX {symbol}: JSON returned no Data rows for expiry={expiry_value}. Keys={list(payload)[:20]}")
    return payload, rows, result["url"]


def get_value(row, *keys):
    for key in keys:
        if row.get(key) not in (None, ""):
            return row.get(key)
    return None


def save_snapshot(conn, symbol, payload, rows, url, captured):
    # Store the complete original JSON as well as metadata; this avoids losing
    # fields whose names may vary between MCX instruments.
    summary = payload.get("Summary") or payload.get("summary") or {}
    first = next((r for r in rows if isinstance(r, dict)), {})
    expiry = get_value(first, "ExpiryDate", "expiryDate", "Expiry", "expiry")
    underlying = None
    for key in ("UnderlyingValue", "Underlying", "UnderlyingPrice", "SpotPrice", "underlyingValue"):
        value = get_value(first, key)
        if value is not None:
            try: underlying = float(value); break
            except (TypeError, ValueError): pass
    # Some responses carry the underlying only in summary/rows; search all rows.
    if underlying is None:
        for row in rows:
            if not isinstance(row, dict): continue
            for key in ("UnderlyingValue", "Underlying", "UnderlyingPrice", "SpotPrice", "underlyingValue"):
                value = row.get(key)
                if value is not None:
                    try: underlying = float(value); break
                    except (TypeError, ValueError): pass
            if underlying is not None: break
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO mcx_option_chain_snapshots
              (snapshot_time, trading_date, symbol, expiry_date, underlying_value, row_count, source_url, summary_data, chain_data)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
        """, (captured, captured.date(), symbol, str(expiry) if expiry else None,
              underlying, len(rows), url, json.dumps(summary), json.dumps(rows)))
    conn.commit()
    print(f"Saved {symbol}: rows={len(rows)}, expiry={expiry}, underlying={underlying}, at={captured.isoformat()}", flush=True)


def main():
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise RuntimeError("Missing SUPABASE_DB_URL GitHub secret")
    now = datetime.now(IST)
    if now.weekday() >= 5 or not (now.time().replace(tzinfo=None) >= datetime.strptime('09:00','%H:%M').time() and now.time().replace(tzinfo=None) <= datetime.strptime('23:59','%H:%M').time()):
        print(f"Outside configured weekday session: {now.isoformat()}; skipping.", flush=True)
        return
    conn = psycopg2.connect(db_url, connect_timeout=15)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            try:
                for symbol in COMMODITIES:
                    captured = datetime.now(IST)
                    try:
                        payload, rows, url = fetch_chain(page, symbol)
                        save_snapshot(conn, symbol, payload, rows, url, captured)
                    except Exception as exc:
                        print(f"FAILED {symbol}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                # Raise failure only if the entire collector failed to save any data.
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM mcx_option_chain_snapshots WHERE snapshot_time >= %s", (now.replace(second=0,microsecond=0),))
                    saved = cur.fetchone()[0]
                if not saved:
                    raise RuntimeError("No commodity snapshots were saved in this run.")
            finally:
                browser.close()
    finally:
        conn.close()

if __name__ == '__main__':
    main()
