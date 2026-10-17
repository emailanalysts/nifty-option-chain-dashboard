import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

PAGE = (
    "https://www.bseindia.com/markets/Derivatives/DeriReports/DeriOptionChain.html"
)

EXPIRY = os.getenv("BSE_EXPIRY", "22 Oct 2026")


def as_num(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def main():
    print("=" * 65)
    print("BSE SENSEX OPTION CHAIN - NETWORK DIAGNOSTICS")
    print("=" * 65)

    print(
        "Run time IST:",
        datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    )
    print("Page:", PAGE)
    print("Requested expiry:", EXPIRY)

    responses = []
    failed_requests = []

    os.makedirs("bse_diagnostics", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="en-IN",
        )

        page = context.new_page()

        def on_response(response):
            url = response.url
            lower_url = url.lower()

            # Monitor potentially relevant BSE responses.
            if (
                "bseindia.com" in lower_url
                and any(
                    word in lower_url
                    for word in [
                        "deriv",
                        "option",
                        "chain",
                        "api",
                    ]
                )
            ):
                try:
                    content_type = response.headers.get(
                        "content-type", ""
                    )
                except Exception:
                    content_type = ""

                item = {
                    "url": url,
                    "status": response.status,
                    "content_type": content_type,
                    "response": response,
                }

                responses.append(item)

                print("\nNETWORK RESPONSE")
                print("HTTP:", response.status)
                print("Content-Type:", content_type)
                print("URL:", url)

        def on_request_failed(request):
            failed_requests.append({
                "url": request.url,
                "failure": (
                    request.failure
                    if hasattr(request, "failure")
                    else "Unknown"
                ),
            })

        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)

        try:
            response = page.goto(
                PAGE,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            print(
                "\nPage HTTP:",
                response.status if response else "No response",
            )
            print("Final URL:", page.url)
            print("Page title:", page.title())

            # Allow page scripts and network requests to run.
            page.wait_for_timeout(15000)

            # Save diagnostics even if no option-chain response appears.
            page.screenshot(
                path="bse_diagnostics/page.png",
                full_page=True,
            )

            with open(
                "bse_diagnostics/page.html",
                "w",
                encoding="utf-8",
            ) as f:
                f.write(page.content())

            print("\n" + "=" * 65)
            print("NETWORK SUMMARY")
            print("=" * 65)

            print("Relevant responses:", len(responses))
            print("Failed requests:", len(failed_requests))

            with open(
                "bse_diagnostics/network_log.json",
                "w",
                encoding="utf-8",
            ) as f:
                json.dump(
                    {
                        "page": PAGE,
                        "final_url": page.url,
                        "page_title": page.title(),
                        "responses": [
                            {
                                "url": r["url"],
                                "status": r["status"],
                                "content_type": r["content_type"],
                            }
                            for r in responses
                        ],
                        "failed_requests": failed_requests,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )

            usable_json = []

            for item in responses:
                url = item["url"]
                status = item["status"]
                content_type = item["content_type"]

                print(
                    f"\nInspecting HTTP {status}: {url}"
                )

                if status != 200:
                    print("Skipping unsuccessful response.")
                    continue

                try:
                    data = item["response"].json()
                except Exception:
                    print(
                        "Response is not valid JSON. "
                        "It may be HTML or another response format."
                    )
                    continue

                if not isinstance(data, dict):
                    print("JSON root is not an object.")
                    continue

                rows = data.get("Table", [])

                if not isinstance(rows, list):
                    rows = []

                print("JSON keys:", list(data.keys()))
                print("Table rows:", len(rows))

                if rows:
                    usable_json.append({
                        "url": url,
                        "data": data,
                        "rows": rows,
                    })

            # Save each response containing populated option-chain rows.
            saved_count = 0

            for index, item in enumerate(usable_json, start=1):
                data = item["data"]
                rows = item["rows"]

                ce_oi = sum(
                    as_num(r.get("C_Open_Interest")) or 0
                    for r in rows
                    if isinstance(r, dict)
                )

                pe_oi = sum(
                    as_num(r.get("Open_Interest")) or 0
                    for r in rows
                    if isinstance(r, dict)
                )

                ce_count = sum(
                    as_num(r.get("C_Open_Interest")) is not None
                    for r in rows
                    if isinstance(r, dict)
                )

                pe_count = sum(
                    as_num(r.get("Open_Interest")) is not None
                    for r in rows
                    if isinstance(r, dict)
                )

                print("\n" + "-" * 50)
                print("USABLE OPTION-CHAIN RESPONSE:", index)
                print("URL:", item["url"])
                print("Rows:", len(rows))
                print("Rows with CE OI:", ce_count)
                print("Rows with PE OI:", pe_count)
                print("Sum CE OI (diagnostic):", int(ce_oi))
                print("Sum PE OI (diagnostic):", int(pe_oi))

                sample = []

                for row in rows:
                    if not isinstance(row, dict):
                        continue

                    if (
                        as_num(row.get("C_Open_Interest")) is not None
                        or as_num(row.get("Open_Interest")) is not None
                    ):
                        sample.append(row)

                    if len(sample) >= 3:
                        break

                print("Sample rows:")
                print(
                    json.dumps(
                        sample,
                        indent=2,
                        ensure_ascii=False,
                    )
                )

                output_path = (
                    f"bse_diagnostics/option_chain_{index}.json"
                )

                with open(
                    output_path,
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump(
                        data,
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )

                print("Saved:", output_path)
                saved_count += 1

            print("\n" + "=" * 65)
            print("FINAL RESULT")
            print("=" * 65)

            if saved_count:
                print(
                    f"SUCCESS: Saved {saved_count} "
                    "option-chain JSON response(s)."
                )
                print(
                    "Expiry selection and data completeness "
                    "still need to be verified."
                )
                return 0

            print("No populated option-chain JSON was found.")
            print("\nNext diagnostic information:")

            if not responses:
                print(
                    "- No matching derivative/option/chain "
                    "responses were observed."
                )
            else:
                print(
                    "- Matching responses were observed, "
                    "but none contained populated Table rows."
                )

            if failed_requests:
                print("\nFailed requests (first 10):")

                for item in failed_requests[:10]:
                    print("URL:", item["url"])
                    print("Failure:", item["failure"])

            print(
                "\nDiagnostic files saved in bse_diagnostics/."
            )

            return 2

        except Exception as exc:
            print(
                "\nPROBE ERROR:",
                type(exc).__name__,
                str(exc),
            )
            return 3

        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
