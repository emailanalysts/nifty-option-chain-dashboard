# Background NSE Snapshot Collector

This is an independent GitHub Actions collector for the NSE Option Chain Dashboard.

## What it does

- Runs automatically on weekdays during 09:15–15:30 IST.
- Fetches current NIFTY and BANKNIFTY nearest-expiry option chains.
- Saves complete option-chain snapshots into the existing Supabase `option_chain_snapshots` table.
- Maintains the fresh daily cumulative COI baseline.
- Runs independently of whether the Streamlit dashboard is open.
- Runs once at 15:30 IST as the final scheduled market snapshot.
- Can also be started manually with **Run workflow**.

## Scheduling note

GitHub Actions scheduled workflows have a minimum supported interval of 5 minutes. Therefore this independent collector runs every 5 minutes, not every 3 minutes. The Streamlit dashboard can still refresh every 3 minutes when it is open.

For a true independent 3-minute collector, move the collector later to a long-running worker/VM or another scheduler that supports sub-5-minute intervals.

## GitHub Secret

Add this repository secret:

`SUPABASE_DB_URL`

Value:

```text
postgresql://postgres.PROJECT_REF:YOUR_PASSWORD@POOLER_HOST:5432/postgres?sslmode=require
```

Use the exact Session Pooler URI from Supabase and replace only the password. Keep the real password in GitHub Secrets; never commit it to the repository.

## Required files

The workflow expects:

- `collector.py`
- `nse_data.py`
- `calculations.py`
- `requirements.txt`
- `.github/workflows/nse_snapshot_collector.yml`

The dashboard files (`app.py` etc.) remain usable as before.
