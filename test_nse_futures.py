import requests
import pandas as pd
from datetime import datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/142.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/",
}

BASE_URL = (
    "https://www.nseindia.com/api/NextApi/apiClient/"
    "GetQuoteApi"
)


def get_futures(symbol):

    session = requests.Session()
    session.headers.update(HEADERS)

    # First visit NSE homepage to establish cookies
    session.get(
        "https://www.nseindia.com/",
        timeout=10
    )

    url = BASE_URL

    params = {
        "functionName": "getSymbolDerivativesData",
        "symbol": symbol
    }

    response = session.get(
        url,
        params=params,
        timeout=10
    )

    print("\nHTTP STATUS:", response.status_code)

    if response.status_code != 200:
        print(response.text[:1000])
        return

    payload = response.json()

    data = payload.get("data", [])

    if not data:
        print("No derivative data returned.")
        print(payload)
        return

    df = pd.DataFrame(data)

    # Only futures
    futures = df[
        df["instrumentType"].astype(str).str.contains(
            "FUT",
            na=False
        )
    ].copy()

    if futures.empty:
        print("No futures contracts found.")
        return

    columns = [
        "identifier",
        "instrumentType",
        "underlying",
        "expiryDate",
        "lastPrice",
        "openInterest",
        "changeInOpenInterest",
        "totalTradedVolume",
        "openPrice",
        "highPrice",
        "lowPrice",
    ]

    columns = [
        c for c in columns
        if c in futures.columns
    ]

    print("\n" + "=" * 70)
    print(symbol, "FUTURES")
    print("=" * 70)

    print(
        futures[columns]
        .sort_values("expiryDate")
        .to_string(index=False)
    )


print("\nNSE FUTURES TEST")
print("Time:", datetime.now())

get_futures("NIFTY")
get_futures("BANKNIFTY")
