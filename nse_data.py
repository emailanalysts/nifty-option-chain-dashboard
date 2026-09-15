import time
import requests
import pandas as pd

NSE_HOME = "https://www.nseindia.com/option-chain"
NSE_API = "https://www.nseindia.com/api"

HEADERS = {
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


def _session():
    s = requests.Session()
    s.headers.update(HEADERS)
    # Establish NSE cookies/session before calling the API.
    r = s.get(NSE_HOME, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"NSE option-chain page returned HTTP {r.status_code}")
    return s


def _nearest_expiry(session, symbol):
    """Get the nearest expiry from NSE's current v3 contract-info endpoint."""
    url = f"{NSE_API}/option-chain-contract-info"
    r = session.get(url, params={"symbol": symbol}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(
            f"NSE contract-info HTTP {r.status_code}: {r.text[:200]}"
        )

    data = r.json()
    expiries = data.get("expiryDates") or data.get("records", {}).get("expiryDates")
    if not expiries:
        raise RuntimeError(f"Could not find expiryDates in NSE response: {list(data.keys())}")

    # NSE normally returns nearest expiry first. Sort defensively.
    parsed = pd.to_datetime(expiries, dayfirst=True, errors="coerce")
    valid = [(d, x) for d, x in zip(parsed, expiries) if not pd.isna(d)]
    if not valid:
        raise RuntimeError(f"Unable to parse NSE expiry dates: {expiries[:5]}")
    return min(valid, key=lambda z: z[0])[1]


def _extract_rows(data):
    """Handle the current v3 response as well as the older filtered/records shape."""
    rows = []

    # Current v3 commonly exposes filtered.data.
    candidates = []
    if isinstance(data.get("filtered"), dict):
        candidates = data["filtered"].get("data") or []
    if not candidates and isinstance(data.get("records"), dict):
        candidates = data["records"].get("data") or []
    if not candidates:
        candidates = data.get("data") or []

    for item in candidates:
        strike = item.get("strikePrice")
        expiry = item.get("expiryDate") or item.get("expiry")
        ce = item.get("CE") or {}
        pe = item.get("PE") or {}

        if strike is None:
            continue

        # v3 can return strike/expiry at option level or inside CE/PE.
        if expiry is None:
            expiry = ce.get("expiryDate") or pe.get("expiryDate")

        rows.append({
            "strikePrice": strike,
            "expiryDate": expiry,
            "CE_OI": ce.get("openInterest", 0),
            "CE_change_OI": ce.get("changeinOpenInterest", ce.get("changeInOpenInterest", 0)),
            "CE_volume": ce.get("totalTradedVolume", 0),
            "CE_IV": ce.get("impliedVolatility", 0),
            "CE_Premium": ce.get("lastPrice", ce.get("lastTradedPrice", 0)),
            "PE_OI": pe.get("openInterest", 0),
            "PE_change_OI": pe.get("changeinOpenInterest", pe.get("changeInOpenInterest", 0)),
            "PE_volume": pe.get("totalTradedVolume", 0),
            "PE_IV": pe.get("impliedVolatility", 0),
            "PE_Premium": pe.get("lastPrice", pe.get("lastTradedPrice", 0)),
            "underlyingValue": (
                item.get("underlyingValue")
                or ce.get("underlyingValue")
                or pe.get("underlyingValue")
            ),
        })

    return pd.DataFrame(rows)


def fetch_option_chain(symbol, retries=4):
    """Fetch the nearest/current expiry option chain using NSE's current v3 API."""
    last_error = None

    for attempt in range(retries):
        try:
            session = _session()
            expiry = _nearest_expiry(session, symbol)

            url = f"{NSE_API}/option-chain-v3"
            params = {
                "type": "Indices",
                "symbol": symbol,
                "expiry": expiry,
            }
            r = session.get(url, params=params, timeout=20)

            if r.status_code != 200:
                raise RuntimeError(
                    f"NSE v3 HTTP {r.status_code}: {r.text[:300]}"
                )

            data = r.json()
            df = _extract_rows(data)

            if df.empty:
                raise RuntimeError(
                    f"NSE v3 returned no option rows. Response keys: {list(data.keys())}"
                )

            # v3 may omit expiry at row level; the requested expiry is authoritative.
            df["expiryDate"] = df["expiryDate"].fillna(expiry)

            return df

        except Exception as e:
            last_error = e
            time.sleep(2 + attempt * 2)

    raise RuntimeError(
        f"Failed to fetch {symbol} option chain after retries: {last_error}"
    )
