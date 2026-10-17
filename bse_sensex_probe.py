#!/usr/bin/env python3
"""Read-only probe for BSE SENSEX option-chain endpoint. No database writes."""
import json, os, sys
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
import requests

BASE = "https://api.bseindia.com/BseIndiaAPI/api/DerivOptionChain_IV/w"
EXPIRY = os.getenv("BSE_EXPIRY", "22 Oct 2026")
SCRIP_CD = os.getenv("BSE_SCRIP_CD", "1")

def number(value):
    if value is None: return None
    s = str(value).strip().replace(",", "")
    if not s: return None
    try: return float(s)
    except ValueError: return None

def main():
    url = BASE + "?" + urlencode({"Expiry": EXPIRY, "scrip_cd": SCRIP_CD, "strprice": "0"})
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/132.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.bseindia.com/markets/Derivatives/DeriReports/DeriOptionChain.aspx",
        "Origin": "https://www.bseindia.com",
    }
    print("BSE SENSEX option-chain read-only probe")
    print("Run time IST:", datetime.now(ZoneInfo("Asia/Kolkata")).isoformat())
    print("Expiry:", EXPIRY)
    print("Endpoint:", BASE)
    try:
        response = requests.get(url, headers=headers, timeout=25)
        print("HTTP:", response.status_code)
        print("Content-Type:", response.headers.get("Content-Type", ""))
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print("PROBE FAILED:", type(exc).__name__, str(exc))
        print("No database writes were attempted.")
        sys.exit(1)
    rows = payload.get("Table", []) if isinstance(payload, dict) else []
    print("Rows returned:", len(rows))
    if not rows:
        print("No rows in Table; response keys:", list(payload) if isinstance(payload, dict) else type(payload).__name__)
        sys.exit(2)
    ce_oi_total = pe_oi_total = ce_volume_total = pe_volume_total = 0.0
    ce_oi_count = pe_oi_count = ce_price_count = pe_price_count = 0
    examples = []
    for row in rows:
        ce_oi, pe_oi = number(row.get("C_Open_Interest")), number(row.get("Open_Interest"))
        ce_px, pe_px = number(row.get("C_Last_Trd_Price")), number(row.get("Last_Trd_Price"))
        ce_vol, pe_vol = number(row.get("C_Vol_Traded")), number(row.get("Vol_Traded"))
        if ce_oi is not None: ce_oi_total += ce_oi; ce_oi_count += 1
        if pe_oi is not None: pe_oi_total += pe_oi; pe_oi_count += 1
        if ce_px is not None: ce_price_count += 1
        if pe_px is not None: pe_price_count += 1
        if ce_vol is not None: ce_volume_total += ce_vol
        if pe_vol is not None: pe_volume_total += pe_vol
        if len(examples) < 8 and any(v is not None for v in (ce_oi, pe_oi, ce_px, pe_px)):
            examples.append({"strike": row.get("Strike_Price1") or row.get("Strike_Price"), "ce_oi": ce_oi, "pe_oi": pe_oi, "ce_ltp": ce_px, "pe_ltp": pe_px, "ce_volume": ce_vol, "pe_volume": pe_vol, "expiry": row.get("End_TimeStamp"), "spot": number(row.get("UlaValue"))})
    print("Strikes with numeric CE OI:", ce_oi_count)
    print("Strikes with numeric PE OI:", pe_oi_count)
    print("Strikes with numeric CE LTP:", ce_price_count)
    print("Strikes with numeric PE LTP:", pe_price_count)
    print("CE OI sum (available rows):", int(ce_oi_total))
    print("PE OI sum (available rows):", int(pe_oi_total))
    print("CE volume sum (available rows):", int(ce_volume_total))
    print("PE volume sum (available rows):", int(pe_volume_total))
    print("Example populated rows:\n", json.dumps(examples, indent=2))
    print("Response keys:", sorted(rows[0].keys()))
    print("READ-ONLY: no Supabase credentials read and no database writes attempted.")
    if ce_oi_count == 0 or pe_oi_count == 0:
        print("WARNING: one or both OI sides have no numeric values; do not integrate yet.")
        sys.exit(3)

if __name__ == "__main__": main()
