"""
Full data refresh - wipe and re-fetch all symbols from AKShare.
Usage: python _refresh_data.py
"""
import sys, time, sqlite3, os
from datetime import datetime, timedelta

# Ensure project root in path
sys.path.insert(0, "C:/futures_demo")
os.chdir("C:/futures_demo")

from loguru import logger
from futures_demo.fetcher import fetch_minute_bars, SYMBOL_EXCHANGE_MAP
from futures_demo.config import load_config
from futures_demo.storage import create_storage
from futures_demo.models import MarketBar

# Configure logging
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

# Config
cfg = load_config("C:/futures_demo/config.yaml")
SYMBOLS = cfg.symbols.symbols
LOOKBACK = cfg.source.lookback_days
DB_PATH = "C:/futures_demo/data/futures_1m.db"

print(f"=== Full Data Refresh ===")
print(f"Symbols: {len(SYMBOLS)} ({SYMBOLS})")
print(f"Lookback: {LOOKBACK} days")
print(f"DB: {DB_PATH}")
print()

# Step 1: Wipe all existing data
print("[1/3] Wiping existing data...")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM bars_1m")
before_count = cur.fetchone()[0]
cur.execute("DELETE FROM bars_1m")
conn.commit()
print(f"  Deleted {before_count} existing rows.")
conn.close()

# Step 2: Re-fetch all symbols
print(f"\n[2/3] Fetching {len(SYMBOLS)} symbols (lookback={LOOKBACK}d)...")
total_bars = 0
total_skipped = 0
errors = []

for i, symbol in enumerate(SYMBOLS, 1):
    variety, contract = symbol[:2], symbol[2:]
    exchange = SYMBOL_EXCHANGE_MAP.get(variety, "SHFE")
    full_sym = f"{symbol}.{exchange}"
    print(f"\n  [{i}/{len(SYMBOLS)}] {full_sym}...", end=" ", flush=True)

    try:
        bars = fetch_minute_bars(symbol, lookback_days=LOOKBACK)
    except Exception as e:
        print(f"ERROR: {e}")
        errors.append((symbol, str(e)))
        time.sleep(0.5)
        continue

    if not bars:
        print("No data (skipped)")
        total_skipped += 1
        time.sleep(0.5)
        continue

    # Batch insert
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    rows = []
    for bar in bars:
        rows.append((
            bar.symbol, bar.exchange.value, bar.ts_ns, bar.freq,
            str(bar.open), str(bar.high), str(bar.low), str(bar.close),
            bar.volume, str(bar.turnover), bar.open_interest,
            bar.source.value, bar.source_ts_ns, bar.received_ts_ns
        ))

    cur.executemany("""
        INSERT OR IGNORE INTO bars_1m
        (symbol, exchange, ts_ns, freq, open, high, low, close,
         volume, turnover, open_interest, source, source_ts_ns, received_ts_ns)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    inserted = cur.rowcount
    conn.close()

    print(f"{len(bars)} bars, {inserted} inserted")
    total_bars += len(bars)
    time.sleep(0.5)

# Step 3: Verify
print(f"\n[3/3] Verifying...")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM bars_1m")
total = cur.fetchone()[0]
cur.execute("""
    SELECT
        symbol,
        COUNT(*) as cnt,
        datetime(MIN(ts_ns)/1e9, 'unixepoch', 'localtime') as first_ts,
        datetime(MAX(ts_ns)/1e9, 'unixepoch', 'localtime') as last_ts
    FROM bars_1m
    GROUP BY symbol
    ORDER BY symbol
""")
rows = cur.fetchall()
conn.close()

print(f"\nTotal bars in DB: {total}")
print(f"\n{'Symbol':25s} {'Count':6s} {'First':22s} {'Last':22s}")
print("-" * 80)
for r in rows:
    print(f"{r[0]:25s} {r[1]:6d} {r[2]:22s} {r[3]:22s}")

print(f"\nSkipped: {total_skipped}, Errors: {len(errors)}")
if errors:
    for sym, err in errors:
        print(f"  ERROR {sym}: {err}")

print(f"\n=== Refresh complete: {total} total bars ===")