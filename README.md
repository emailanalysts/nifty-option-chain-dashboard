# NSE Option Chain Dashboard — Supabase DB Status version

This version uses Supabase PostgreSQL for persistent option-chain snapshots and shows a Database Status indicator at the top of the dashboard.

## Streamlit Secrets

In Streamlit Community Cloud → App settings → Secrets:

```toml
[connections.postgresql]
url = "postgresql://postgres.PROJECT_REF:YOUR_PASSWORD@POOLER_HOST:5432/postgres?sslmode=require"
```

Never commit the real password to GitHub.

## Supabase table

The app expects the existing `option_chain_snapshots` table created by the project SQL setup.
