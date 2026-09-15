NSE Option Chain Dashboard

This is a chart-only dashboard. It does NOT use the BUDDY V1-V16 engine.

Charts:

NIFTY COI

BANKNIFTY COI

Overall Open Interest

NIFTY Strike Price-wise OI

BANKNIFTY Strike Price-wise OI

NIFTY Max Pain

BANKNIFTY Max Pain

Run

pip install -r requirements.txt
streamlit run app.py

Open the Streamlit URL shown in the terminal.

COI

COI is built from intraday snapshots saved in SQLite.

For each new snapshot:

CE delta = current total CE OI - previous total CE OI
PE delta = current total PE OI - previous total PE OI
COI increment = PE delta - CE delta

The dashboard stores the cumulative COI curve.

Keep the app running during market hours and use Refresh now periodically.

Important

NSE may occasionally block automated requests. The data layer therefore creates a fresh session, visits the NSE homepage first, retries failed requests, and validates the JSON response.