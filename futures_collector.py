import os
import requests
import pandas as pd

from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg2


# ============================================================
# SETTINGS
# ============================================================

IST = ZoneInfo("Asia/Kolkata")

NSE_URL = (
    "https://www.nseindia.com/api/NextApi/apiClient/"
    "GetQuoteApi"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/142.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.nseindia.com/",
}


# ============================================================
# SUPABASE DATABASE CONNECTION
# ============================================================

def get_database_url():

    url = os.getenv("SUPABASE_DB_URL")

    if not url:
        raise RuntimeError(
            "SUPABASE_DB_URL environment variable is not set."
        )

    return url


def connect_database():

    return psycopg2.connect(
        get_database_url(),
        connect_timeout=15,
        sslmode="require"
    )


# ============================================================
# NSE MARKET HOURS
# ============================================================

def is_market_hours():

    now = datetime.now(IST)

    # Saturday / Sunday
    if now.weekday() >= 5:
        return False

    market_open = now.replace(
        hour=9,
        minute=15,
        second=0,
        microsecond=0
    )

    market_close = now.replace(
        hour=15,
        minute=40,
        second=0,
        microsecond=0
    )

    return market_open <= now <= market_close


# ============================================================
# 5-MINUTE TIMESTAMP
# ============================================================

def get_5min_timestamp():

    now = datetime.now(IST)

    minute = (now.minute // 5) * 5

    timestamp = now.replace(
        minute=minute,
        second=0,
        microsecond=0
    )

    return timestamp


# ============================================================
# NSE SESSION
# ============================================================

def create_nse_session():

    session = requests.Session()

    session.headers.update(HEADERS)

    try:

        response = session.get(
            "https://www.nseindia.com/",
            timeout=15
        )

        print(
            "NSE homepage:",
            response.status_code
        )

    except Exception as e:

        print(
            "NSE homepage request failed:",
            e
        )

    return session


# ============================================================
# GET FUTURES DATA
# ============================================================

def get_futures(session, symbol):

    params = {
        "functionName": "getSymbolDerivativesData",
        "symbol": symbol,
    }

    response = session.get(
        NSE_URL,
        params=params,
        timeout=15
    )

    print(
        f"{symbol} API:",
        response.status_code
    )

    response.raise_for_status()

    payload = response.json()

    data = payload.get("data", [])

    if not data:

        raise RuntimeError(
            f"No futures data returned for {symbol}"
        )

    df = pd.DataFrame(data)

    # Only index futures
    df = df[
        df["instrumentType"]
        .astype(str)
        .str.upper()
        .eq("FUTIDX")
    ].copy()

    if df.empty:

        raise RuntimeError(
            f"No FUTIDX contracts found for {symbol}"
        )

    return df


# ============================================================
# SELECT NEAREST EXPIRY
# ============================================================

def select_nearest_future(df):

    df = df.copy()

    df["expiry_dt"] = pd.to_datetime(
        df["expiryDate"],
        format="%d-%b-%Y",
        errors="coerce"
    )

    today = datetime.now(IST).date()

    df = df[
        df["expiry_dt"].notna()
        & (
            df["expiry_dt"].dt.date >= today
        )
    ].copy()

    if df.empty:

        raise RuntimeError(
            "No current/future expiry found."
        )

    nearest_expiry = df["expiry_dt"].min()

    result = df[
        df["expiry_dt"] == nearest_expiry
    ].copy()

    if result.empty:

        raise RuntimeError(
            "Unable to select nearest futures contract."
        )

    return result.iloc[0]


# ============================================================
# SAFE PYTHON VALUE CONVERSION
# ============================================================

def to_python_value(value):

    if value is None:
        return None

    try:

        if pd.isna(value):
            return None

    except Exception:
        pass

    # Convert numpy scalar -> native Python scalar
    if hasattr(value, "item"):

        try:
            return value.item()

        except Exception:
            pass

    return value


# ============================================================
# COLLECT NIFTY + BANKNIFTY
# ============================================================

def collect_snapshot():

    session = create_nse_session()

    snapshot_time = get_5min_timestamp()

    records = []

    for symbol in (
        "NIFTY",
        "BANKNIFTY",
    ):

        print()
        print(
            f"Collecting {symbol} Futures..."
        )

        df = get_futures(
            session,
            symbol
        )

        row = select_nearest_future(df)

        # ----------------------------------------------------
        # Identifier
        # ----------------------------------------------------

        identifier = row.get("identifier")

        if identifier is not None:
            identifier = str(identifier)

        # ----------------------------------------------------
        # Expiry
        # ----------------------------------------------------

        expiry_value = row["expiry_dt"]

        if pd.isna(expiry_value):

            expiry_date = None

        else:

            expiry_date = expiry_value.date()

        # ----------------------------------------------------
        # Last Price
        # ----------------------------------------------------

        last_price_raw = pd.to_numeric(
            row.get("lastPrice"),
            errors="coerce"
        )

        if pd.isna(last_price_raw):

            last_price = None

        else:

            last_price = float(
                last_price_raw
            )

        # ----------------------------------------------------
        # Volume
        # ----------------------------------------------------

        volume_raw = pd.to_numeric(
            row.get("totalTradedVolume"),
            errors="coerce"
        )

        if pd.isna(volume_raw):

            volume = None

        else:

            volume = int(
                volume_raw
            )

        # ----------------------------------------------------
        # Open Interest
        # ----------------------------------------------------

        oi_raw = pd.to_numeric(
            row.get("openInterest"),
            errors="coerce"
        )

        if pd.isna(oi_raw):

            open_interest = None

        else:

            open_interest = int(
                oi_raw
            )

        # ----------------------------------------------------
        # Create record
        # ----------------------------------------------------

        record = {

            "snapshot_time":
                snapshot_time,

            "trading_date":
                snapshot_time.date(),

            "symbol":
                str(symbol),

            "expiry_date":
                expiry_date,

            "identifier":
                identifier,

            "open_price":
                None,

            "high_price":
                None,

            "low_price":
                None,

            "last_price":
                last_price,

            "volume":
                volume,

            "open_interest":
                open_interest,

            "change_in_oi":
                None,

            "source":
                "NSE_LIVE",
        }

        # ----------------------------------------------------
        # Final safety conversion
        # ----------------------------------------------------

        for key in record:

            record[key] = to_python_value(
                record[key]
            )

        records.append(record)

    return records


# ============================================================
# CALCULATE 5-MINUTE OI CHANGE
# ============================================================

def calculate_oi_changes(records):

    with connect_database() as con:

        with con.cursor() as cur:

            for record in records:

                cur.execute(
                    """
                    SELECT open_interest
                    FROM futures_5m_snapshots
                    WHERE symbol = %s
                      AND trading_date = %s
                    ORDER BY snapshot_time DESC
                    LIMIT 1
                    """,
                    (
                        str(record["symbol"]),
                        record["trading_date"],
                    )
                )

                row = cur.fetchone()

                if row is not None:

                    previous_oi = row[0]

                    if (
                        previous_oi is not None
                        and record["open_interest"] is not None
                    ):

                        record["change_in_oi"] = float(
                            record["open_interest"]
                        ) - float(
                            previous_oi
                        )

                        # Force native Python float
                        record["change_in_oi"] = float(
                            record["change_in_oi"]
                        )

    return records


# ============================================================
# CALCULATE SYNTHETIC 5-MINUTE OHLC
# ============================================================

def calculate_5m_ohlc(records):

    """
    Build reconstructed 5-minute OHLC from successive
    NSE live prices.

    IMPORTANT:
    This is NOT native NSE 5-minute OHLC.

    It reconstructs a simple candle using the previous
    stored price and the current live price:

        Open  = previous snapshot price
        High  = max(previous, current)
        Low   = min(previous, current)
        Close = current snapshot price
    """

    with connect_database() as con:

        with con.cursor() as cur:

            for record in records:

                current_price = record["last_price"]

                if current_price is None:

                    record["open_price"] = None
                    record["high_price"] = None
                    record["low_price"] = None

                    continue

                # ------------------------------------------------
                # Find previous stored price
                # ------------------------------------------------

                cur.execute(
                    """
                    SELECT last_price
                    FROM futures_5m_snapshots
                    WHERE symbol = %s
                      AND trading_date = %s
                    ORDER BY snapshot_time DESC
                    LIMIT 1
                    """,
                    (
                        str(record["symbol"]),
                        record["trading_date"],
                    )
                )

                row = cur.fetchone()

                # ------------------------------------------------
                # First snapshot of the day
                # ------------------------------------------------

                if (
                    row is None
                    or row[0] is None
                ):

                    previous_price = float(
                        current_price
                    )

                else:

                    previous_price = float(
                        row[0]
                    )

                current_price = float(
                    current_price
                )

                # ------------------------------------------------
                # Synthetic 5-minute candle
                # ------------------------------------------------

                record["open_price"] = float(
                    previous_price
                )

                record["high_price"] = float(
                    max(
                        previous_price,
                        current_price
                    )
                )

                record["low_price"] = float(
                    min(
                        previous_price,
                        current_price
                    )
                )

    return records


# ============================================================
# INSERT INTO SUPABASE
# ============================================================

def save_records(records):

    insert_sql = """
        INSERT INTO futures_5m_snapshots
        (
            snapshot_time,
            trading_date,
            symbol,
            expiry_date,
            identifier,
            open_price,
            high_price,
            low_price,
            last_price,
            volume,
            open_interest,
            change_in_oi,
            source
        )
        VALUES
        (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        ON CONFLICT
        (
            symbol,
            trading_date,
            expiry_date,
            snapshot_time
        )
        DO NOTHING
    """

    inserted = 0

    with connect_database() as con:

        with con.cursor() as cur:

            for record in records:

                params = (

                    record["snapshot_time"],

                    record["trading_date"],

                    str(
                        record["symbol"]
                    ),

                    record["expiry_date"],

                    record["identifier"],

                    (
                        float(
                            record["open_price"]
                        )
                        if record["open_price"] is not None
                        else None
                    ),

                    (
                        float(
                            record["high_price"]
                        )
                        if record["high_price"] is not None
                        else None
                    ),

                    (
                        float(
                            record["low_price"]
                        )
                        if record["low_price"] is not None
                        else None
                    ),

                    (
                        float(
                            record["last_price"]
                        )
                        if record["last_price"] is not None
                        else None
                    ),

                    (
                        int(
                            record["volume"]
                        )
                        if record["volume"] is not None
                        else None
                    ),

                    (
                        int(
                            record["open_interest"]
                        )
                        if record["open_interest"] is not None
                        else None
                    ),

                    (
                        float(
                            record["change_in_oi"]
                        )
                        if record["change_in_oi"] is not None
                        else None
                    ),

                    str(
                        record["source"]
                    ),
                )

                cur.execute(
                    insert_sql,
                    params
                )

                # rowcount = 1 means inserted
                # rowcount = 0 means duplicate

                if cur.rowcount == 1:

                    inserted += 1

        con.commit()

    return inserted


# ============================================================
# DISPLAY RESULT
# ============================================================

def display_records(records):

    print()

    print("=" * 90)
    print("FUTURES 5-MINUTE SNAPSHOT")
    print("=" * 90)

    for record in records:

        print()

        print(
            f"Symbol       : "
            f"{record['symbol']}"
        )

        print(
            f"Snapshot     : "
            f"{record['snapshot_time']}"
        )

        print(
            f"Expiry       : "
            f"{record['expiry_date']}"
        )

        print(
            f"5-min Open   : "
            f"{record['open_price']}"
        )

        print(
            f"5-min High   : "
            f"{record['high_price']}"
        )

        print(
            f"5-min Low    : "
            f"{record['low_price']}"
        )

        print(
            f"Last Price   : "
            f"{record['last_price']}"
        )

        print(
            f"Volume       : "
            f"{record['volume']}"
        )

        print(
            f"Open Interest: "
            f"{record['open_interest']}"
        )

        print(
            f"5-min OI Δ   : "
            f"{record['change_in_oi']}"
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print()

    print("=" * 90)
    print("NSE FUTURES → SUPABASE 5-MIN COLLECTOR")
    print("=" * 90)

    now = datetime.now(IST)

    print(
        "IST:",
        now.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    print()

    # --------------------------------------------------------
    # MARKET HOURS
    # --------------------------------------------------------

    if not is_market_hours():

        print(
            "Outside NSE equity-derivatives market hours."
        )

        print(
            "Allowed: 09:15–15:40 IST"
        )

        print(
            "No database write performed."
        )

        raise SystemExit(0)

    # --------------------------------------------------------
    # COLLECT
    # --------------------------------------------------------

    try:

        records = collect_snapshot()

        # ----------------------------------------------------
        # CALCULATE OI CHANGE
        # ----------------------------------------------------

        records = calculate_oi_changes(
            records
        )

        # ----------------------------------------------------
        # CALCULATE SYNTHETIC 5-MIN OHLC
        # ----------------------------------------------------

        records = calculate_5m_ohlc(
            records
        )

        # ----------------------------------------------------
        # DISPLAY
        # ----------------------------------------------------

        display_records(
            records
        )

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        inserted = save_records(
            records
        )

        print()

        print("=" * 90)

        print(
            f"Inserted {inserted} records into Supabase."
        )

        print("=" * 90)

    except Exception as e:

        print()

        print("=" * 90)
        print("COLLECTOR ERROR")
        print("=" * 90)

        print(
            type(e).__name__,
            ":",
            str(e)
        )
