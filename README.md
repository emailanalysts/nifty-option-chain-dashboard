# NSE Option Chain Dashboard

A Streamlit dashboard for NIFTY and BANKNIFTY current-expiry option-chain analysis.

## Charts

1. NIFTY COI
2. BANKNIFTY COI
3. Overall Open Interest
4. NIFTY Strike Price-wise OI
5. BANKNIFTY Strike Price-wise OI
6. NIFTY Max Pain
7. BANKNIFTY Max Pain

## Market-hours behavior

- **09:15–15:30 IST, Monday–Friday:** fetch fresh NSE data and refresh every 3 minutes while the dashboard session is active.
- **After 15:30 IST:** no NSE calls; show the latest completed trading-day snapshot.
- **Before 09:15 IST:** no NSE calls; show the most recent previous trading-day snapshot.
- **Saturday/Sunday:** no NSE calls; show the most recent saved trading-day snapshot.
- A new trading day starts a fresh COI baseline; previous-day COI is never carried forward.

The 15:30 snapshot is captured if a dashboard refresh occurs at/through 15:30. Because Streamlit's 3-minute fragment is session-driven, a refresh that occurs slightly before 15:30 may be the last captured snapshot. A separate background scheduler can be added later if an exact 15:30 collector is required even when nobody has the dashboard open.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Important cloud note

The current version stores complete snapshots in a local SQLite file so the dashboard can reproduce prior-day charts without calling NSE after market close. Streamlit Community Cloud local storage is not guaranteed to be permanent across app restarts/redeployments. For durable historical data, move the snapshot store to a persistent cloud database (for example PostgreSQL/Supabase) and optionally run the collector as a separate scheduled job.

## NSE connectivity

NSE may occasionally block automated requests. The data layer creates a fresh session, visits the NSE option-chain page first, retries failed requests, and validates the JSON response.
