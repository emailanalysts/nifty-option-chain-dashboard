# Read-only Option-Chain Benchmark

This script compares:
1. NSE NIFTY option-chain fetch using the same three-step approach as the existing dashboard helper.
2. FYERS NIFTY option-chain API.
3. FYERS SENSEX option-chain API.

It does not write to Supabase, edit the dashboard, or print credentials.

## Requirements
Run from the same Python 3.11 virtual environment where `fyers-apiv3` is installed. The script also needs `requests` and `pandas` (typically already installed in the project environment).

## Run on Windows PowerShell
Open PowerShell in the folder containing `benchmark_optionchain.py` and `fyers_access_token.txt`, activate the `fyers311` environment, then set the app ID in that terminal:

```powershell
$env:FYERS_APP_ID = "YOUR_ACTUAL_APP_ID"
python -u .\benchmark_optionchain.py
```

The script reads the access token from `fyers_access_token.txt` by default. It never displays the token. If the token file is elsewhere, set `FYERS_TOKEN_FILE` to its path.

## Timing
For meaningful results, run on a regular trading weekday between 9:15 AM and 3:30 PM IST. Outside those hours, the script asks before continuing. It performs 3 trials per source with a short pause between trials; the whole run may take longer if NSE is slow.

## Measurements and limitations
- NSE payload bytes: actual response-body bytes summed across homepage, expiry lookup, and option-chain requests.
- FYERS payload bytes: estimated size of the SDK response after serializing its returned JSON. This is not exact network usage; HTTP headers, TLS overhead, and any compression are not measured.
- Times measure request path elapsed time. They include NSE's session setup and expiry lookup, but FYERS uses a single option-chain API call. This reflects the current implementation paths, not a perfectly identical request count.
- NSE may return HTTP errors or block requests. The script records the failure; it does not try to bypass access controls.
- The script benchmarks option-chain requests only. It does not benchmark futures yet because the current front-month FYERS futures symbol/contract discovery needs separate validation.
- The three providers may return different numbers of strikes, so compare payload size alongside entries returned.
- It makes no Supabase writes and does not alter existing collectors.

The script creates timestamped CSV and JSON result files in the current folder. Share the printed summary and relevant CSV rows, but never share API secrets, authorization codes, or access tokens.
