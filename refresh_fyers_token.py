import os
import sys
import hashlib
import requests

APP_ID = os.environ["FYERS_APP_ID"]
APP_SECRET = os.environ["FYERS_APP_SECRET"]
REFRESH_TOKEN = os.environ["FYERS_REFRESH_TOKEN"]
PIN = os.environ["FYERS_PIN"]

# FYERS appIdHash = SHA-256 of app_id:app_secret
app_id_hash = hashlib.sha256(
    f"{APP_ID}:{APP_SECRET}".encode("utf-8")
).hexdigest()

url = "https://api-t1.fyers.in/api/v3/validate-refresh-token"

payload = {
    "grant_type": "refresh_token",
    "appIdHash": app_id_hash,
    "refresh_token": REFRESH_TOKEN,
    "pin": PIN,
}

try:
    response = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )

    print("FYERS refresh HTTP status:", response.status_code)

    try:
        result = response.json()
    except ValueError:
        print("FYERS returned a non-JSON response.")
        print("Response preview:", response.text[:500])
        sys.exit(1)
    
    if response.status_code >= 400:
        print("FYERS rejected the refresh request.")
        print("FYERS status:", result.get("s"))
        print("FYERS code:", result.get("code"))
        print("FYERS message:", result.get("message"))
        sys.exit(1)

    if result.get("s") != "ok" or not result.get("access_token"):
        print("FYERS token refresh failed.")
        print("Status:", result.get("s"))
        print("Code:", result.get("code"))
        print("Message:", result.get("message"))
        sys.exit(1)

    # Pass the token to the collector without printing it.
    with open("fyers_access_token.txt", "w", encoding="utf-8") as f:
        f.write(result["access_token"])

    print("FYERS access token refreshed successfully.")

except requests.RequestException as exc:
    print("FYERS refresh request failed:", type(exc).__name__)
    sys.exit(1)
