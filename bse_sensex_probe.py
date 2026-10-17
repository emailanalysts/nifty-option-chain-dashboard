"""Read-only diagnostic for public BSE SENSEX data endpoints.
Does not write to Supabase or change the production dashboard.
Run with: python bse_sensex_probe.py
"""
import json
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

IST = ZoneInfo("Asia/Kolkata")
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}


def report(label, url, response):
    print(f"\n=== {label} ===")
    print("URL:", url)
    print("HTTP:", response.status_code)
    print("Content-Type:", response.headers.get("Content-Type", ""))
    body = response.text[:1400].replace("\r", " ")
    try:
        obj = response.json()
        if isinstance(obj, dict):
            print("JSON top-level keys:", list(obj.keys())[:40])
        elif isinstance(obj, list):
            print("JSON list length:", len(obj))
            if obj and isinstance(obj[0], dict):
                print("First-row keys:", list(obj[0].keys())[:40])
        print("Response preview:", json.dumps(obj, ensure_ascii=False)[:1400])
    except Exception:
        print("Response preview:", body)


def main():
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    print("BSE SENSEX diagnostic (read-only)")
    print("Run time IST:", datetime.now(IST).isoformat(timespec="seconds"))

    # Known public SENSEX quote endpoint. This is only an index quote, not derivatives.
    quote_url = "https://api.bseindia.com/RealTimeBseIndiaAPI/api/GetSensexData/w"
    try:
        r = session.get(quote_url, timeout=20)
        report("Public SENSEX index quote", quote_url, r)
    except Exception as exc:
        print("\n=== Public SENSEX index quote ===\nRequest failed:", repr(exc))

    # Load the official BSE derivatives page and list possible API paths found in its HTML.
    page_url = "https://www.bseindia.com/markets/Derivatives/DeriReports/DeriOptionChain.aspx"
    try:
        r = session.get(page_url, timeout=20)
        report("Official BSE derivatives option-chain page", page_url, r)
        html = r.text
        matches = sorted(set(re.findall(r"[^\"' ]*(?:api/|OptionChain|optionchain|Deriv)[^\"' ]*", html, flags=re.I)))
        print("Candidate page references (first 60):")
        for item in matches[:60]:
            print(" ", item[:300])
        if not matches:
            print(" No matching endpoint references found in page HTML.")
    except Exception as exc:
        print("\n=== Official BSE derivatives option-chain page ===\nRequest failed:", repr(exc))

    print("\n=== Interpretation ===")
    print("A successful index quote does NOT prove option-chain or futures data is accessible.")
    print("Use this output to confirm whether a public endpoint returns CE/PE OI and futures prices before production integration.")
    print("No credentials, environment variables, or database writes are used by this diagnostic.")


if __name__ == "__main__":
    main()
