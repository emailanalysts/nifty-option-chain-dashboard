import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

PAGE = "https://www.bseindia.com/markets/Derivatives/DeriReports/DeriOptionChain.aspx"
EXPIRY = os.getenv("BSE_EXPIRY", "22 Oct 2026")

def as_num(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None

def main():
    print("BSE SENSEX browser-assisted option-chain probe (read-only)")
    print("Run time IST:", datetime.now(ZoneInfo("Asia/Kolkata")).isoformat())
    print("Page:", PAGE)
    print("Expiry requested:", EXPIRY)
    captured = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="en-IN")
        def on_response(response):
            if "DerivOptionChain_IV" in response.url:
                captured.append((response, response.url))
        page.on("response", on_response)
        try:
            resp = page.goto(PAGE, wait_until="domcontentloaded", timeout=60000)
            print("Page HTTP:", resp.status if resp else "no response")
            page.wait_for_timeout(12000)
            # On the official page, try to select the expiry if a visible expiry control exists.
            # Do not attempt to bypass CAPTCHA or other access controls.
            if not captured:
                print("No option-chain JSON response captured on initial page load.")
                print("Page title:", page.title())
                print("Page URL:", page.url)
                print("This may mean the page requires an interactive selection, or access is restricted.")
                return 2
            for response, url in captured:
                print("Captured API HTTP:", response.status)
                print("Captured API URL:", url)
                try:
                    data = response.json()
                except Exception as exc:
                    print("Response was not JSON:", type(exc).__name__, str(exc))
                    continue
                rows = data.get("Table", []) if isinstance(data, dict) else []
                if not isinstance(rows, list):
                    rows = []
                ce_oi = sum(as_num(r.get("C_Open_Interest")) or 0 for r in rows if isinstance(r, dict))
                pe_oi = sum(as_num(r.get("Open_Interest")) or 0 for r in rows if isinstance(r, dict))
                ce_count = sum(as_num(r.get("C_Open_Interest")) is not None for r in rows if isinstance(r, dict))
                pe_count = sum(as_num(r.get("Open_Interest")) is not None for r in rows if isinstance(r, dict))
                print("Rows:", len(rows))
                print("Rows with numeric CE OI:", ce_count)
                print("Rows with numeric PE OI:", pe_count)
                print("Sum CE OI (diagnostic only):", int(ce_oi))
                print("Sum PE OI (diagnostic only):", int(pe_oi))
                if rows:
                    sample = []
                    for r in rows:
                        if not isinstance(r, dict):
                            continue
                        if as_num(r.get("C_Open_Interest")) is not None or as_num(r.get("Open_Interest")) is not None:
                            sample.append({k: r.get(k) for k in ["Strike_Price", "Strike_Price1", "C_Open_Interest", "C_Absolute_Change_OI", "C_Last_Trd_Price", "C_Vol_Traded", "Open_Interest", "Absolute_Change_OI", "Last_Trd_Price", "Vol_Traded", "UlaValue", "End_TimeStamp"] if k in r})
                        if len(sample) >= 3:
                            break
                    print("Sample populated rows:")
                    print(json.dumps(sample, indent=2, ensure_ascii=False))
                    with open("sensex_browser_probe.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    print("Saved response as sensex_browser_probe.json (workflow artifact will be uploaded).")
                    browser.close()
                    return 0
            print("A matching request was seen, but no usable Table rows were parsed.")
            return 3
        finally:
            try:
                browser.close()
            except Exception:
                pass

if __name__ == "__main__":
    sys.exit(main())
