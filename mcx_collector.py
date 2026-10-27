"""Collect MCX commodity option-chain snapshots into PostgreSQL/Supabase.

Required environment variable: SUPABASE_DB_URL
Expected table: mcx_option_chain_snapshots (see README.txt).
"""
import json
import os
import sys
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

import psycopg2
from playwright.sync_api import sync_playwright

IST = ZoneInfo("Asia/Kolkata")
BASE = "https://www.mcxindia.com"
LANDING = f"{BASE}/market-data/option-chain"
COMMODITIES = ("GOLD", "SILVER", "CRUDEOIL", "NATURALGAS")
SESSION_START = dt_time(9, 0)
SESSION_END = dt_time(23, 59)
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def in_session(now):
    return now.weekday() < 5 and SESSION_START <= now.timetz().replace(tzinfo=None) <= SESSION_END


def select_commodity(page, symbol):
    selects = page.locator("select")
    for i in range(selects.count()):
        select = selects.nth(i)
        options = select.locator("option")
        for j in range(options.count()):
            opt = options.nth(j)
            value = (opt.get_attribute("value") or "").strip()
            label = (opt.inner_text() or "").strip()
            if value.upper() == symbol or label.upper() == symbol:
                select.select_option(value=value)
                return select
    raise RuntimeError(f"Could not find {symbol} in MCX commodity dropdowns ({selects.count()} select elements found). MCX may have changed or blocked the page.")


def select_expiry(page):
    selects = page.locator("select")
    for i in range(selects.count()):
        select = selects.nth(i)
        options = select.locator("option")
        # Do not treat the commodity selector as the expiry selector.
        option_texts = []
        for j in range(options.count()):
            opt = options.nth(j)
            value = (opt.get_attribute("value") or "").strip()
            label = (opt.inner_text() or "").strip()
            option_texts.append((value, label))
        if any(v.upper() in COMMODITIES or l.upper() in COMMODITIES for v, l in option_texts):
            continue
        candidates = [v for v, l in option_texts
                      if v and v.lower() not in ("0", "-1", "select", "none")
                      and any(m in (v + " " + l).lower() for m in MONTHS)]
        if candidates:
            select.select_option(value=candidates[0])
            return candidates[0]
    raise RuntimeError("Could not identify an expiry dropdown with date/month options.")


def fetch_chain(page, symbol):
    page.goto(LANDING, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    
    title = page.title() or ""
    body_text = page.locator("body").inner_text(timeout=10000) or ""
    
    print(f"MCX page title: {title}", flush=True)
    print(f"MCX page URL: {page.url}", flush=True)
    print(f"MCX page text (first 1000 chars): {body_text[:1000]!r}", flush=True)
    
    if "access denied" in title.lower() or "access denied" in body_text.lower():
        raise RuntimeError("MCX returned an Access Denied page in this browser session.")
        
    select_commodity(page, symbol)
    page.wait_for_timeout(900)
    expiry = select_expiry(page)
    show = page.get_by_role("button", name="Show")
    if show.count():
        show.first.click(timeout=10000)
        page.wait_for_timeout(900)

    endpoint = f"{BASE}/GetOptionChain?InstrumentType=optfut&Symbol={symbol}&Expiry={expiry}"
    result = page.evaluate("""async (url) => {
      const r = await fetch(url, {method:'GET', credentials:'include', headers:{
        'X-Requested-With':'XMLHttpRequest',
        'Accept':'application/json, text/javascript, */*; q=0.01'
      }});
      return {status:r.status, url:r.url, text:await r.text()};
    }""", endpoint)
    if result["status"] != 200:
        raise RuntimeError(f"MCX {symbol} expiry={expiry}: HTTP {result['status']}; response={result['text'][:250]!r}")
    try:
        payload = json.loads(result["text"])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"MCX {symbol} response was not JSON: {result['text'][:250]!r}") from exc
    rows = payload.get("Data") or payload.get("data") or []
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"No option-chain rows for {symbol}/{expiry}; keys={list(payload)[:20]}")
    return payload, rows, result["url"], expiry


def save_snapshot(conn, symbol, payload, rows, url, expiry, captured):
    summary = payload.get("Summary") or payload.get("summary") or {}
    underlying = None
    underlying_keys = ("UnderlyingValue", "Underlying", "UnderlyingPrice", "SpotPrice", "underlyingValue")
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in underlying_keys:
            value = row.get(key)
            if value not in (None, ""):
                try:
                    underlying = float(value)
                    break
                except (TypeError, ValueError):
                    pass
        if underlying is not None:
            break

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO mcx_option_chain_snapshots
              (snapshot_time, trading_date, symbol, expiry_date, underlying_value,
               row_count, source_url, summary_data, chain_data)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
        """, (captured, captured.date(), symbol, str(expiry) if expiry else None,
              underlying, len(rows), url, json.dumps(summary), json.dumps(rows)))
    conn.commit()
    print(f"SAVED {symbol}: rows={len(rows)}, expiry={expiry}, underlying={underlying}, time={captured.isoformat()}", flush=True)


def main():
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise RuntimeError("Missing SUPABASE_DB_URL GitHub Actions secret.")
    now = datetime.now(IST)
    if not in_session(now):
        print(f"Outside weekday session 09:00-23:59 IST: {now.isoformat()}; skipping.", flush=True)
        return

    conn = psycopg2.connect(db_url, connect_timeout=20)
    saved, failed = 0, []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                locale="en-IN", timezone_id="Asia/Kolkata"
            )
            page = context.new_page()
            page.set_default_timeout(15000)
            try:
                for symbol in COMMODITIES:
                    try:
                        payload, rows, url, expiry = fetch_chain(page, symbol)
                        save_snapshot(conn, symbol, payload, rows, url, expiry, datetime.now(IST))
                        saved += 1
                    except Exception as exc:
                        failed.append(symbol)
                        print(f"FAILED {symbol}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            finally:
                context.close()
                browser.close()
    finally:
        conn.close()

    print(
        f"Collection complete: saved={saved}/4; "
        f"failed={','.join(failed) if failed else 'none'}",
        flush=True
    )
    
    if failed:
        raise RuntimeError(
            f"MCX collection incomplete: saved={saved}/4; "
            f"failed={','.join(failed)}"
        )

if __name__ == "__main__":
    main()
