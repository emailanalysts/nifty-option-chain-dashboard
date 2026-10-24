"""
MCX Commodity Collector — Browser Diagnostic Version

Purpose:
1. Open the official MCX option-chain page using Playwright.
2. Inspect the page controls and available commodity/expiry options.
3. Save a screenshot and HTML snapshot for debugging.
4. Make no database changes.

Run:
    python mcx_collector.py

Requirements:
    pip install playwright
    python -m playwright install chromium
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright


IST = ZoneInfo("Asia/Kolkata")

MCX_URL = (
    "https://www.mcxindia.com/market-data/option-chain"
)

OUTPUT_DIR = Path("mcx_diagnostics")

COMMODITIES = [
    "GOLD",
    "SILVER",
    "CRUDEOIL",
    "NATURALGAS",
]


async def inspect_page(page):
    """Inspect the rendered page and return diagnostic details."""

    result = await page.evaluate(
        """() => {
            const visible = (el) => {
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();

                return (
                    s.display !== 'none' &&
                    s.visibility !== 'hidden' &&
                    r.width > 0 &&
                    r.height > 0
                );
            };

            const describe = (el) => ({
                tag: el.tagName,
                text: (el.innerText || el.textContent || '')
                    .trim()
                    .slice(0, 250),
                value: el.value || null,
                id: el.id || null,
                name: el.getAttribute('name'),
                role: el.getAttribute('role'),
                ariaLabel: el.getAttribute('aria-label'),
                ariaHaspopup: el.getAttribute('aria-haspopup'),
                className:
                    typeof el.className === 'string'
                        ? el.className.slice(0, 250)
                        : null
            });

            return {
                url: location.href,
                title: document.title,
                readyState: document.readyState,

                selectCount:
                    document.querySelectorAll('select').length,

                selects: Array.from(
                    document.querySelectorAll('select')
                ).map(el => ({
                    ...describe(el),
                    options: Array.from(el.options).map(o => ({
                        text: o.textContent.trim(),
                        value: o.value
                    }))
                })),

                visibleInputs: Array.from(
                    document.querySelectorAll('input')
                ).filter(visible).map(describe),

                visibleButtons: Array.from(
                    document.querySelectorAll('button')
                ).filter(visible).map(describe),

                visibleComboboxes: Array.from(
                    document.querySelectorAll(
                        '[role="combobox"]'
                    )
                ).filter(visible).map(describe),

                visibleListboxes: Array.from(
                    document.querySelectorAll(
                        '[role="listbox"]'
                    )
                ).filter(visible).map(describe),

                visibleOptionElements: Array.from(
                    document.querySelectorAll(
                        '[role="option"]'
                    )
                ).filter(visible).map(describe),

                visibleDropdownLikeElements: Array.from(
                    document.querySelectorAll(
                        '[aria-haspopup], .dropdown, ' +
                        '[class*="select"], [class*="dropdown"]'
                    )
                ).filter(visible).slice(0, 100).map(describe),

                bodyText:
                    document.body.innerText.slice(0, 12000)
            };
        }"""
    )

    return result


async def main():
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    timestamp = datetime.now(IST).strftime(
        "%Y%m%d_%H%M%S"
    )

    print("=" * 70)
    print("MCX OPTION-CHAIN PAGE DIAGNOSTIC")
    print("=" * 70)
    print("Time IST:", datetime.now(IST).isoformat())
    print("Page:", MCX_URL)
    print("Database writes: DISABLED")
    print()

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        context = await browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000
            },
            locale="en-IN",
            timezone_id="Asia/Kolkata"
        )

        page = await context.new_page()

        # Record the option-chain API requests initiated by the site.
        api_responses = []

        async def response_handler(response):
            if "GetOptionChain" in response.url:
                item = {
                    "url": response.url,
                    "status": response.status,
                    "content_type": response.headers.get(
                        "content-type"
                    )
                }

                api_responses.append(item)

                print("\nOPTION-CHAIN RESPONSE DETECTED")
                print(json.dumps(item, indent=2))

        page.on("response", response_handler)

        try:
            response = await page.goto(
                MCX_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            print(
                "Initial HTTP status:",
                response.status if response else "Unavailable"
            )

            # Allow the site's JavaScript to initialize.
            await page.wait_for_timeout(7000)

            # Capture the page after JavaScript initialization.
            screenshot_path = (
                OUTPUT_DIR /
                f"mcx_page_{timestamp}.png"
            )

            html_path = (
                OUTPUT_DIR /
                f"mcx_page_{timestamp}.html"
            )

            json_path = (
                OUTPUT_DIR /
                f"mcx_diagnostic_{timestamp}.json"
            )

            await page.screenshot(
                path=str(screenshot_path),
                full_page=True
            )

            html = await page.content()

            html_path.write_text(
                html,
                encoding="utf-8"
            )

            details = await inspect_page(page)

            details["initial_http_status"] = (
                response.status if response else None
            )

            details["captured_api_responses"] = api_responses

            json_path.write_text(
                json.dumps(
                    details,
                    indent=2,
                    ensure_ascii=False
                ),
                encoding="utf-8"
            )

            print("\nPAGE DIAGNOSTICS")
            print("-" * 70)

            print(
                "Final URL:",
                details["url"]
            )

            print(
                "Page title:",
                details["title"]
            )

            print(
                "Document ready state:",
                details["readyState"]
            )

            print(
                "HTML select elements:",
                details["selectCount"]
            )

            print(
                "Visible inputs:",
                len(details["visibleInputs"])
            )

            print(
                "Visible buttons:",
                len(details["visibleButtons"])
            )

            print(
                "Visible comboboxes:",
                len(details["visibleComboboxes"])
            )

            print(
                "Visible listboxes:",
                len(details["visibleListboxes"])
            )

            print("\nVISIBLE BUTTONS")
            print(
                json.dumps(
                    details["visibleButtons"],
                    indent=2,
                    ensure_ascii=False
                )
            )

            print("\nVISIBLE COMBOBOXES")
            print(
                json.dumps(
                    details["visibleComboboxes"],
                    indent=2,
                    ensure_ascii=False
                )
            )

            print("\nVISIBLE INPUTS")
            print(
                json.dumps(
                    details["visibleInputs"],
                    indent=2,
                    ensure_ascii=False
                )
            )

            print("\nDROPDOWN-LIKE ELEMENTS")
            print(
                json.dumps(
                    details["visibleDropdownLikeElements"],
                    indent=2,
                    ensure_ascii=False
                )
            )

            print("\nPAGE TEXT PREVIEW")
            print(details["bodyText"][:6000])

            print("\nCOMMODITY LABELS FOUND IN PAGE TEXT")

            body_upper = details["bodyText"].upper()

            for commodity in COMMODITIES:
                print(
                    f"{commodity}: "
                    f"{commodity in body_upper}"
                )

            print("\nCAPTURED OPTION-CHAIN REQUESTS")
            print(
                json.dumps(
                    api_responses,
                    indent=2
                )
            )

            print("\nFILES CREATED")
            print("Screenshot:", screenshot_path)
            print("HTML:", html_path)
            print("Diagnostic JSON:", json_path)

            print(
                "\nNo database writes were performed."
            )

        except Exception as exc:
            print(
                "\nDIAGNOSTIC FAILED:",
                type(exc).__name__,
                str(exc)
            )

            try:
                error_path = (
                    OUTPUT_DIR /
                    f"mcx_error_{timestamp}.png"
                )

                await page.screenshot(
                    path=str(error_path),
                    full_page=True
                )

                print(
                    "Error screenshot:",
                    error_path
                )

            except Exception:
                pass

            raise

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
