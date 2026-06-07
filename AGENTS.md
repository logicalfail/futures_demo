# Futures Terminal — Agent Guide

> Chinese futures market data visualization terminal (AKShare → SQLite/TimescaleDB → FastAPI → React SPA).

## Quick start

```powershell
# One-click launch (auto-builds frontend if needed):
.\start.bat                # Windows CMD
.\start.ps1 -Mode prod     # PowerShell production
.\start.ps1 -Mode dev      # Dev mode (hot-reload backend, frontend via `cd frontend && npm run dev`)

# Or directly:
$env:PYTHONPATH='C:\futures_demo'; python -m uvicorn server.app:create_app --factory --port 8000

# Frontend dev server (separate terminal):
cd frontend && npm run dev     # port 5173, proxies /api and /ws to port 8000

# Data pipeline:
python demo.py                                     # quick demo, all symbols
python -m futures_demo.pipeline fetch              # one-shot fetch all
python -m futures_demo.pipeline loop               # continuous (minute interval)
python -m futures_demo.pipeline verify             # quality check on stored data
python _refresh_data.py                            # wipe + full re-fetch

# Tests:
$env:PYTHONPATH='C:\futures_demo'; python -m pytest tests/ -v
python tests/test_server_phase1.py                 # run directly (no pytest needed)
python tests/test_integration_phase3.py            # needs built frontend dist/
```

## Project layout

```
C:\futures_demo\
├── futures_demo/        # Data layer (pure Python, no FastAPI dependency)
│   ├── fetcher.py       #   AKShare minute bar fetcher (Sina + EastMoney)
│   ├── storage.py       #   SQLite / TimescaleDB storage abstraction
│   ├── models.py        #   MarketBar Pydantic model, contract multipliers
│   ├── quality.py       #   Data quality checks (gaps, outliers, zero-volume)
│   ├── config.py        #   Data-layer config loader (reads config.yaml)
│   └── vnpy_adapter.py  #   Optional vnpy BarData conversion
├── server/              # FastAPI service layer
│   ├── app.py           #   App factory create_app() — WS + REST + static files
│   ├── config.py        #   Server config loader (reads server_config.yaml)
│   ├── data_service.py  #   Query/cache/poll orchestration
│   ├── connection_manager.py  # WebSocket connection pool
│   ├── scheduler.py     #   Async minute-level polling scheduler
│   ├── aggregation.py   #   1m → 5m/15m/1h/1d aggregation
│   ├── dominant.py      #   Dominant contract resolution + rollover chaining
│   └── routers/v1.py    #   /api/v1/* endpoints for strategy modules
├── frontend/            # React + Vite + ECharts SPA
│   ├── src/api/         #   HTTP API wrappers
│   ├── src/hooks/       #   useWebSocket hook (auto-reconnect, subscribe)
│   └── src/components/  #   KLineChart, QuoteTable, SymbolSelector, StatusBar
├── tests/               # E2E tests (no unit tests)
│   ├── test_server_phase1.py      # Backend REST + WS tests
│   └── test_integration_phase3.py # Frontend+Backend integration
├── docs/                # Design docs per phase
├── config.yaml          # Data layer config (symbols, source, storage, scheduler, quality)
└── server_config.yaml   # Server config (host, port, scheduler, storage)
```

## Critical gotchas

### Two config files, never confuse them
- **`config.yaml`** — loaded by `futures_demo.config.load_config()` (caches globally)
- **`server_config.yaml`** — loaded by `server.config.load_config()` (no global cache)
- Server's `DataService` also loads `config.yaml` internally for symbol lists.

### PYTHONPATH is required
Every script/test must have `C:\futures_demo` in `sys.path`. Both test files do this via `sys.path.insert(0, ...)`. When running directly: `$env:PYTHONPATH='C:\futures_demo'`.

### Timestamp: pd.Timestamp.timestamp() is WRONG
```python
# ❌ BUG: pandas Timestamp.timestamp() treats naive datetime as UTC
ts_ns = int(dt.timestamp() * 1e9)          # +8h offset for Chinese futures

# ✅ CORRECT: convert to Python datetime first
ts_ns = int(dt.to_pydatetime().timestamp() * 1e9)
```
This was a real bug (2026-06-07) that caused all timestamps to be 8h off. Data was fully re-fetched.

### AKShare/Sina API limitations
- Only returns **last 5 trading days** of minute data
- Rate limit: **≥0.2s** between requests (ideally 0.5s), or Sina throttles
- No data outside trading hours and weekends
- Column names vary: Sina returns English `datetime,open,high,low,close,volume,hold`; EastMoney returns Chinese columns `时间,开盘,最高,最低,收盘,成交量`

### Test DB is separate
Tests use `./data/futures_1m_test.db` — never touches the production `futures_1m.db`. But both can exist simultaneously.

### Tests always disable the scheduler
```python
cfg.scheduler.enabled = False  # required in every test setup
```
Otherwise the background loop races with test assertions and causes flaky failures.

### WebSocket tests are non-trivial
`test_server_phase1.py` uses `asyncio` + external server on port 8001 (skips if not running).
`test_integration_phase3.py` uses `TestClient.websocket_connect()` + a **threading-based** non-blocking receive helper (because asyncio doesn't work with TestClient's sync WS). Patterns:
- Use `ws_recv(ws, timeout)` instead of `ws.receive_text()` for non-blocking reads
- Always expect possible timeouts; wrap in loops

### Frontend must be built for production
`start.bat` auto-detects missing dist/ and builds. `start.ps1 prod` does the same. But tests (`test_integration_phase3.py`) expect `frontend/dist/index.html` to exist — tests fail gracefully with `[SKIP]` if not built.

### start.bat: NO Chinese characters
CMD.exe uses GBK encoding, not UTF-8. `start.bat` must be ASCII-only. All Unicode (Chinese, emoji, box-drawing) goes in `start.ps1` only. This was a real bug.

### Symbol format: short vs full
- Short: `RB2609`, `AU2608` (variety code + contract month)
- Full: `RB2609.SHFE`, `AU2608.SHFE` (appended exchange suffix)
- Server auto-completes via `data_service.full_symbol()`
- The `.` separator is critical for parsing — `RB2609.SHFE` means variety=`RB`, exchange=`SHFE`

### Night session times vary by product
Config uses a wide net (21:00-23:30), but reality is more nuanced:
- AU/AG (precious metals): 21:00-02:30
- CU/AL/ZN (base metals): 21:00-01:00
- Most others: 21:00-23:00
See `docs/KNOWLEDGE.md` for the full matrix.

### Data layer has its own global config cache
`futures_demo.config.load_config()` uses a module-level `_config` global. Once loaded, `get_config()` returns the cached version. If tests need to force-reload config, reset `futures_demo.config._config = None`.

### Server uses factory pattern
`uvicorn` must be called with `--factory` flag: `uvicorn server.app:create_app --factory`. The function `create_app()` returns a new `FastAPI` instance each call.

## Commands reference

| Action | Command |
|--------|---------|
| Dominant contract bars | `GET /api/v1/dominant/{variety}?rollover=chain&limit=5` | 主力合约分钟K线，自动换月适配 |
| Query bars (aggregated) | `GET /api/v1/bars/{symbol}?period=5m&limit=10` | 历史K线，支持多周期聚合 |
| Start server (foreground) | `.\start.bat` or `.\start.bat 9000 0.0.0.0` (port, host) |
| Start server (background, bat exits) | `.\start.bat --bg` (logs: `server.log`) |
| Start server (background, auto-open browser) | `.\start_bg.bat` (kills old instance, opens http://...) |
| Start server (background PowerShell) | `.\start.ps1 -Mode devbg` |
| Start server (dev, hot-reload) | `.\start.ps1 -Mode dev` |
| Frontend dev server | `cd frontend && npm run dev` (port 5173) |
| Build frontend | `cd frontend && npm run build` |
| Fetch data once | `python -m futures_demo.pipeline fetch` |
| Continuous collection | `python -m futures_demo.pipeline loop` |
| Daily dominant pull | 自动，每日 23:59 服务器调度器触发 |
| Quality verify | `python -m futures_demo.pipeline verify` |
| Run all tests | `$env:PYTHONPATH='C:\futures_demo'; python -m pytest tests/ -v` |
| Run backend tests only | `python tests/test_server_phase1.py` |
| Run integration tests | `python tests/test_integration_phase3.py` |
| Full data refresh | `python _refresh_data.py` |

## Test structure

- **`test_server_phase1.py`** — REST API + WS connectivity, standalone runnable, async WS test requires a running server on port 8001
- **`test_integration_phase3.py`** — Frontend static serving + SPA routing + WS subscribe/kline/ping-pong/manual-refresh + REST coverage, uses `TestClient`, expects `frontend/dist/` built

CI pattern: Run Phase 1 first (standalone), build frontend, then run Phase 3.
