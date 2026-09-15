from pathlib import Path
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

DB = Path(__file__).with_name("option_chain_history.db")
IST = ZoneInfo("Asia/Kolkata")

def prepare_chain(df, symbol):
    df = df.copy()
    df["expiryDate"] = pd.to_datetime(df["expiryDate"], dayfirst=True, errors="coerce")
    df["strikePrice"] = pd.to_numeric(df["strikePrice"], errors="coerce")
    numeric_cols = ["CE_OI","CE_change_OI","CE_volume","CE_IV","CE_Premium","PE_OI","PE_change_OI","PE_volume","PE_IV","PE_Premium","underlyingValue"]
    for c in numeric_cols:
        if c not in df.columns: df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    today = pd.Timestamp.now(tz=IST).tz_localize(None).normalize()
    future = df.loc[df["expiryDate"] >= today, "expiryDate"]
    expiry = future.min() if not future.empty else df["expiryDate"].max()
    df = df[df["expiryDate"] == expiry].copy().sort_values("strikePrice").reset_index(drop=True)
    df["symbol"] = symbol
    return df

def atm_strike(df):
    spot = float(df["underlyingValue"].iloc[0])
    idx = (df["strikePrice"] - spot).abs().idxmin()
    return float(df.loc[idx, "strikePrice"])

def strike_wise_oi(df, window=10):
    atm = atm_strike(df); strikes = sorted(df["strikePrice"].unique())
    nearest = min(range(len(strikes)), key=lambda i: abs(strikes[i] - atm))
    return df[df["strikePrice"].isin(strikes[max(0,nearest-window):min(len(strikes),nearest+window+1)])][["strikePrice","CE_OI","PE_OI"]].sort_values("strikePrice")

def max_pain(df, return_table=False):
    strikes=np.sort(df["strikePrice"].unique()); calls=df.groupby("strikePrice")["CE_OI"].sum(); puts=df.groupby("strikePrice")["PE_OI"].sum(); pain=[]
    for settlement in strikes:
        call_pain=sum(max(0.0,settlement-k)*calls.get(k,0) for k in strikes)
        put_pain=sum(max(0.0,k-settlement)*puts.get(k,0) for k in strikes)
        pain.append((settlement,call_pain+put_pain))
    out=pd.DataFrame(pain,columns=["strikePrice","totalPain"]); mp=float(out.loc[out["totalPain"].idxmin(),"strikePrice"])
    return (mp,out) if return_table else mp

def overall_oi(nifty, bank):
    return {"NIFTY":{"CE":int(nifty["CE_OI"].sum()),"PE":int(nifty["PE_OI"].sum())},"BANKNIFTY":{"CE":int(bank["CE_OI"].sum()),"PE":int(bank["PE_OI"].sum())}}

def current_coi(df): return float(df["PE_change_OI"].sum()-df["CE_change_OI"].sum())

def _init_db():
    with sqlite3.connect(DB) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp TEXT NOT NULL,symbol TEXT NOT NULL,expiry TEXT NOT NULL,spot REAL,ce_oi REAL,pe_oi REAL,coi_increment REAL,cumulative_coi REAL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS snapshot_chain (id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp TEXT NOT NULL,symbol TEXT NOT NULL,expiry TEXT NOT NULL,strikePrice REAL NOT NULL,CE_OI REAL,CE_change_OI REAL,CE_volume REAL,CE_IV REAL,CE_Premium REAL,PE_OI REAL,PE_change_OI REAL,PE_volume REAL,PE_IV REAL,PE_Premium REAL,underlyingValue REAL)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_time ON snapshots(symbol,timestamp)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_chain_symbol_time ON snapshot_chain(symbol,timestamp)")
        con.commit()

def save_snapshot(df):
    _init_db(); symbol=str(df["symbol"].iloc[0]); expiry=str(pd.Timestamp(df["expiryDate"].iloc[0]).date()); spot=float(df["underlyingValue"].iloc[0]); ce_oi=float(df["CE_OI"].sum()); pe_oi=float(df["PE_OI"].sum()); now=datetime.now(IST).replace(second=0,microsecond=0); today=now.date().isoformat()
    with sqlite3.connect(DB) as con:
        prev=pd.read_sql_query("SELECT ce_oi,pe_oi,cumulative_coi FROM snapshots WHERE symbol=? AND expiry=? AND substr(timestamp,1,10)=? ORDER BY timestamp DESC LIMIT 1",con,params=(symbol,expiry,today))
        if prev.empty: increment=cumulative=0.0
        else:
            increment=(pe_oi-float(prev.iloc[0]["pe_oi"]))-(ce_oi-float(prev.iloc[0]["ce_oi"])); cumulative=float(prev.iloc[0]["cumulative_coi"])+increment
        con.execute("DELETE FROM snapshots WHERE symbol=? AND timestamp=?",(symbol,now.isoformat())); con.execute("DELETE FROM snapshot_chain WHERE symbol=? AND timestamp=?",(symbol,now.isoformat()))
        con.execute("INSERT INTO snapshots (timestamp,symbol,expiry,spot,ce_oi,pe_oi,coi_increment,cumulative_coi) VALUES (?,?,?,?,?,?,?,?)",(now.isoformat(),symbol,expiry,spot,ce_oi,pe_oi,increment,cumulative))
        rows=[]
        for _,r in df.iterrows(): rows.append((now.isoformat(),symbol,expiry,float(r["strikePrice"]),float(r["CE_OI"]),float(r["CE_change_OI"]),float(r["CE_volume"]),float(r["CE_IV"]),float(r["CE_Premium"]),float(r["PE_OI"]),float(r["PE_change_OI"]),float(r["PE_volume"]),float(r["PE_IV"]),float(r["PE_Premium"]),float(r["underlyingValue"])))
        con.executemany("INSERT INTO snapshot_chain (timestamp,symbol,expiry,strikePrice,CE_OI,CE_change_OI,CE_volume,CE_IV,CE_Premium,PE_OI,PE_change_OI,PE_volume,PE_IV,PE_Premium,underlyingValue) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",rows); con.commit()

def load_intraday_history(symbol,trading_date=None):
    _init_db(); date_str=trading_date or datetime.now(IST).date().isoformat()
    with sqlite3.connect(DB) as con: df=pd.read_sql_query("SELECT timestamp,symbol,expiry,spot,ce_oi,pe_oi,coi_increment,cumulative_coi FROM snapshots WHERE symbol=? AND substr(timestamp,1,10)=? ORDER BY timestamp",con,params=(symbol,date_str))
    if not df.empty: df["timestamp"]=pd.to_datetime(df["timestamp"])
    return df

def latest_saved_trading_date(symbol):
    _init_db()
    with sqlite3.connect(DB) as con: row=con.execute("SELECT substr(timestamp,1,10) FROM snapshots WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",(symbol,)).fetchone()
    return row[0] if row else None

def load_latest_snapshot(symbol):
    return load_latest_snapshot_on_or_before(symbol, datetime.now(IST).date().isoformat())

def load_latest_snapshot_on_or_before(symbol,trading_date):
    _init_db()
    with sqlite3.connect(DB) as con:
        row=con.execute("SELECT timestamp FROM snapshot_chain WHERE symbol=? AND substr(timestamp,1,10)<=? ORDER BY timestamp DESC LIMIT 1",(symbol,trading_date,)).fetchone()
        if not row: return pd.DataFrame()
        df=pd.read_sql_query("SELECT strikePrice,expiry,CE_OI,CE_change_OI,CE_volume,CE_IV,CE_Premium,PE_OI,PE_change_OI,PE_volume,PE_IV,PE_Premium,underlyingValue FROM snapshot_chain WHERE symbol=? AND timestamp=? ORDER BY strikePrice",con,params=(symbol,row[0]))
    df["expiryDate"]=pd.to_datetime(df["expiry"],errors="coerce"); df["symbol"]=symbol; return df

def load_coi_history_for_latest_day(symbol,on_or_before=None):
    date_str=on_or_before or latest_saved_trading_date(symbol)
    return load_intraday_history(symbol,date_str) if date_str else pd.DataFrame()
