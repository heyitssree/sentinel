# The Sentinel: Multimodal Alpha Engine - Implementation Plan

A high-availability paper trading pipeline integrating Zerodha (mock), DuckDB, and Gemini 2.0 Flash for sentiment-weighted, vision-audited trade decisions.

---

## Phase 3 Implementation Summary (Mar 9, 2026 - Audit Refinements)

### Completed Changes

| Phase | Component | File | Description |
|-------|-----------|------|-------------|
| **0** | SDK Upgrade | `requirements.txt` | Migrated to `google-genai[aiohttp]` (replaces legacy SDK) |
| **0** | Pydantic Models | `src/gemini/models.py` | Structured outputs for all Gemini responses |
| **0** | Async Sentiment | `src/gemini/sentiment.py` | Async client + Pydantic schema (no JSON parsing) |
| **0** | Thinking Mode | `src/gemini/autopsy.py` | Deep reasoning for complex trade analysis |
| **0** | Technical Analyst | `src/gemini/technical_analyst.py` | Async + structured outputs |
| **1** | Thread Safety | `main.py` | `threading.Lock()` for `_candle_data` access |
| **1** | Parallel Processing | `main.py` | `ThreadPoolExecutor` for ticker analysis |
| **1** | SSL Security | `src/api/server.py` | SSL bypass only in dev mode (`SENTINEL_DEV_MODE=true`) |
| **1** | Data Retention | `src/storage/db.py` | `vacuum_old_data(days=7)` method |
| **2** | VWAP Pullback | `src/trading/signals.py` | Mean Reversion Filter (replaces RSI>60) |
| **2** | Volume Gate | `src/trading/signals.py` | 1.5x volume confirmation required |
| **2** | ATR Stops | `src/trading/signals.py` | Dynamic SL=2×ATR, TP=4×ATR |
| **3** | MTF Confluence | `src/trading/signals.py` | 1-hour trend confirmation for 5-min signals |
| **3** | Hourly Aggregation | `src/storage/db.py` | `aggregate_to_hourly()` from 5-min data |
| **3** | Regime Detection | `src/gemini/regime_detector.py` | TRENDING_UP/DOWN/CHOPPY classification |
| **3** | Kill Switch Integration | `src/trading/risk.py` | Regime multiplier (50% in CHOPPY) |

### New Trading Logic: Mean Reversion Filter

**OLD (Lagging):**
```
Entry: Price > 200 EMA + RSI > 60 + Price > VWAP
```

**NEW (Improved RR):**
```
Entry: Price > 200 EMA + VWAP Pullback (within 0.5%) + Volume > 1.5x avg
Stops: SL = 2×ATR, TP = 4×ATR (adapts to stock volatility)
```

### New Settings (`config/settings.py`)

```python
# Mean Reversion Filter
VWAP_PULLBACK_THRESHOLD = 0.005  # 0.5% buffer zone
VOLUME_CONFIRMATION_MULTIPLIER = 1.5
VOLUME_OVERRIDES = {}  # Per-stock: "RELIANCE:1.2,TCS:2.0"

# Dynamic ATR Stops
ATR_STOP_LOSS_MULTIPLIER = 2.0
ATR_TAKE_PROFIT_MULTIPLIER = 4.0

# Database
DATA_RETENTION_DAYS = 7
```

### Regime Detection Timing

- **9:20 AM IST** - First check (after opening volatility settles)
- **Every 30 min** - Subsequent checks

### Kill Switch Regime Integration

When CHOPPY regime detected:
- `DEFAULT_QUANTITY` reduced by 50%
- Kill switch limit reduced by 50% (₹5000 → ₹2500)

---

## Phase 2 Implementation Summary (Mar 9, 2026)

### Completed Features

| Component | File | Description |
|-----------|------|-------------|
| **Nifty 50 Config** | `config/nifty50.py` | Full 50 stocks with sectors, instrument tokens, index weights |
| **Volume Spike Detection** | `src/signals/indicators.py` | `detect_volume_spike()` and `get_volume_spike_info()` methods |
| **Trading Phase Manager** | `src/trading/schedule.py` | OBSERVATION → ACTIVE → SQUAREOFF → POSTMARKET phases |
| **Daily Autopsy Markdown** | `src/gemini/autopsy.py` | `generate_daily_markdown()` for in-app reports |
| **Phase 2 API Endpoints** | `src/api/server.py` | Confluence, chart-data, heatmap, autopsy, MTM limit |
| **AI Reasoning Panel** | `frontend/src/components/AIReasoningPanel.jsx` | Sentiment gauge, confluence checkmarks, reasoning log |
| **Technical Heatmap** | `frontend/src/components/TechnicalHeatmap.jsx` | Full Nifty 50 RSI grid with sector grouping |
| **Trading Chart** | `frontend/src/components/TradingChart.jsx` | Lightweight-charts with EMA/VWAP overlays |
| **Daily Autopsy Panel** | `frontend/src/components/DailyAutopsy.jsx` | Markdown-rendered Gemini analysis |

### New API Endpoints

- `GET /api/signals/{ticker}/confluence` - Detailed multi-factor confluence status
- `GET /api/chart-data/{ticker}` - OHLCV + indicators for lightweight-charts
- `GET /api/schedule/phase` - Current trading phase info
- `GET /api/heatmap/nifty50` - RSI + volume spike for all 50 stocks
- `GET /api/autopsy/daily` - Gemini-generated daily Markdown report
- `GET/POST /api/risk/mtm-limit` - User-configurable MTM limit

### Design Decisions

- **Heatmap**: Full Nifty 50 with sector grouping (not just watchlist)
- **Daily Report**: In-app Markdown panel (not PDF/email)
- **Trading**: LONG positions only for Phase 2
- **Historical Data**: Zerodha `kite.historical_data()` for 200 EMA accuracy

### Frontend Dependencies Added

```json
{
  "lightweight-charts": "^4.1.0",
  "react-markdown": "^9.0.0",
  "remark-gfm": "^4.0.0"
}
```

### Bug Fixes (Mar 9, 2026 - Session 2)

| Issue | Fix | File |
|-------|-----|------|
| DuckDB missing `interval` column | Added migration to add column if missing | `src/storage/db.py` |
| `numpy.bool` serialization error | Convert all numpy types to Python native in heatmap/confluence | `src/api/server.py` |
| `ConfluenceResult.confluence_met` AttributeError | Changed to `result.is_valid` | `src/api/server.py` |
| TradingChart candle format mismatch | Handle both `time` and `timestamp` fields, deduplicate | `TradingChart.jsx` |
| TradingChart indicator format | API returns `{time, value}` objects, not arrays | `TradingChart.jsx` |
| Sentiment always -1 | Was deriving from confluence confidence, added real `/api/sentiment/{ticker}` endpoint | `server.py`, `AIReasoningPanel.jsx` |
| Gemini model deprecated | Updated from `gemini-2.0-flash` to `gemini-2.5-flash` | `sentiment.py` |
| Mock sentiment always used | Enabled real `SentimentAnalyzer` with API key from `.env` | `server.py` |
| News only for watchlist | Removed watchlist filter, now fetches for all Nifty 50 | `news_scraper.py` |
| News cache not persisting | Added global cache with TTL to persist across API calls | `news_scraper.py` |

### Features Added (Mar 9, 2026 - Session 2)

| Feature | Description | File |
|---------|-------------|------|
| More news sources | Added 5 more RSS feeds (8 total) | `news_scraper.py` |
| Manual stock input | Text input to add any NSE ticker | `App.jsx` |
| Auto news refresh | Background loop refreshes news every 5 min | `server.py` |
| Startup news fetch | Initial fetch for all Nifty 50 on server start | `server.py` |

---

## Architecture Overview

```
┌─────────────────┐    ┌──────────────┐    ┌─────────────────┐
│  Data Ingestion │───▶│   DuckDB     │───▶│  Signal Engine  │
│  (Mock Kite +   │    │  (OHLC, News)│    │  (VWAP+RSI+EMA) │
│   RSS Feeds)    │    └──────────────┘    └────────┬────────┘
└─────────────────┘                                 │
                                                    ▼
┌─────────────────┐    ┌──────────────┐    ┌─────────────────┐
│  Paper Trade    │◀───│   Gemini     │◀───│  Gemini Audit   │
│  Executor       │    │  Decision    │    │  (News + Chart) │
└─────────────────┘    └──────────────┘    └─────────────────┘
```

---

## Phase 1: Project Foundation

### 1.1 Directory Structure
```
/Users/sree/sentinel/
├── config/
│   └── settings.py          # API keys, watchlist, thresholds
├── data/
│   └── sentinel.duckdb      # Time-series database
├── src/
│   ├── ingestion/
│   │   ├── mock_kite.py     # Mock Zerodha WebSocket
│   │   └── news_scraper.py  # RSS feed parser (ET, Moneycontrol)
│   ├── storage/
│   │   └── db.py            # DuckDB operations
│   ├── signals/
│   │   └── indicators.py    # VWAP, RSI, EMA calculations
│   ├── gemini/
│   │   ├── sentiment.py     # Feature A: Vibe-Weighted Entry
│   │   ├── vision.py        # Feature B: Visual Auditor
│   │   └── autopsy.py       # Feature C: Post-Trade Review
│   ├── trading/
│   │   ├── executor.py      # Paper trade execution (0.05% slippage)
│   │   └── risk.py          # Kill switch, 10 OPS limit
│   └── charts/
│       └── generator.py     # Matplotlib chart → PNG
├── main.py                   # Heartbeat loop orchestrator
├── requirements.txt
└── README.md
```

### 1.2 Dependencies
- `duckdb` - Embedded analytics DB
- `pandas`, `numpy` - Data manipulation
- `feedparser` - RSS parsing
- `google-generativeai` - Gemini 2.0 Flash API
- `matplotlib`, `mplfinance` - Chart generation
- `schedule` - Task scheduling
- `python-dotenv` - Env management

---

## Phase 2: Data Ingestion Layer

### 2.1 Mock Kite Class (`mock_kite.py`)
- Simulate WebSocket tick stream for 5 stocks: `RELIANCE, ICICIBANK, TCS, INFY, HDFCBANK`
- Generate realistic OHLCV data with random walk + volatility
- Swappable interface: `MockKite` ↔ `KiteConnect` (same method signatures)

### 2.2 News Scraper (`news_scraper.py`)
- Parse RSS feeds from Economic Times & Moneycontrol
- Filter headlines by stock ticker keywords
- Store in DuckDB with timestamp + ticker association

### 2.3 DuckDB Schema (`db.py`)
```sql
-- OHLCV candles (5-min interval)
CREATE TABLE candles (
    ticker VARCHAR, timestamp TIMESTAMP, 
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT
);

-- News headlines
CREATE TABLE news (
    ticker VARCHAR, timestamp TIMESTAMP, 
    headline TEXT, source VARCHAR
);

-- Paper trades
CREATE TABLE trades (
    id INTEGER PRIMARY KEY, ticker VARCHAR, 
    entry_time TIMESTAMP, exit_time TIMESTAMP,
    entry_price DOUBLE, exit_price DOUBLE,
    quantity INTEGER, pnl DOUBLE, reason TEXT
);
```

---

## Phase 3: Signal Engine

### 3.1 Technical Indicators (`indicators.py`)
- **VWAP**: Volume-weighted average price (intraday reset)
- **RSI(14)**: Relative Strength Index
- **EMA(20)**: Exponential Moving Average

### 3.2 Entry Condition
```python
def should_trigger_audit(candle, vwap, rsi, ema20):
    return candle.close > vwap and rsi > 60 and candle.close > ema20
```

---

## Phase 4: Gemini Integration

### 4.1 Feature A: Vibe-Weighted Entry (`sentiment.py`)
- Input: Last 10 headlines for ticker from DuckDB
- Prompt: "Analyze headlines. Return sentiment score (-1 to 1) focusing on earnings/regulatory news."
- Gate: If sentiment < 0, cancel trade

### 4.2 Feature B: Visual Auditor (`vision.py`)
- Input: 15-min + 1-hour candle chart PNGs (generated via Matplotlib)
- Prompt: "Looking for breakout. Is chart overextended (RSI>80) or clean pattern? Answer: SAFE or RISKY"
- Gate: If "RISKY", cancel trade

### 4.3 Feature C: Post-Trade Autopsy (`autopsy.py`)
- Trigger: 3:30 PM IST daily
- Input: All trades + tick data from DuckDB
- Prompt: "Review trades. Did I exit too early? Suggest one stop-loss tweak."
- Output: Log recommendations to file

---

## Phase 5: Trading & Risk

### 5.1 Paper Executor (`executor.py`)
- Simulate market order with **0.05% slippage**
- Track open positions, calculate MTM in real-time
- Log all trades to DuckDB `trades` table

### 5.2 Risk Controls (`risk.py`)
- **10 OPS Limit**: Rate limiter (token bucket)
- **Kill Switch**: Hard-coded ₹5,000 MTM loss → disconnect all, close positions
- **Market Hours Guard**: Only operate 9:15 AM - 3:30 PM IST

---

## Phase 6: Main Orchestrator

### 6.1 Heartbeat Loop (`main.py`)
```python
while True:
    if not is_market_open():  # 9:15 AM - 3:30 PM IST
        if is_closing_time():
            run_autopsy()
            close_all_positions()
        sleep(60)
        continue
    
    for ticker in WATCHLIST:
        fetch_and_store_candles(ticker)
        fetch_and_store_news(ticker)
        
        if should_trigger_audit(ticker):
            sentiment = gemini_sentiment_check(ticker)
            chart_safety = gemini_vision_check(ticker)
            
            if sentiment > 0 and chart_safety == "SAFE":
                execute_paper_trade(ticker)
    
    check_kill_switch()
    sleep(300)  # 5-minute candle interval
```

---

## Implementation Order

| Step | Component | Est. Time |
|------|-----------|-----------|
| 1 | Project setup, `requirements.txt`, config | 15 min |
| 2 | DuckDB schema + operations | 20 min |
| 3 | Mock Kite (realistic tick simulation) | 30 min |
| 4 | RSS news scraper | 20 min |
| 5 | Technical indicators (VWAP, RSI, EMA) | 25 min |
| 6 | Chart generator (Matplotlib) | 20 min |
| 7 | Gemini sentiment module | 20 min |
| 8 | Gemini vision module | 20 min |
| 9 | Paper trade executor + risk controls | 30 min |
| 10 | Main heartbeat orchestrator | 20 min |
| 11 | Post-trade autopsy | 15 min |
| 12 | README + testing | 15 min |

---

## Environment Variables Required
```env
GEMINI_API_KEY=your_gemini_api_key_here
MTM_LOSS_LIMIT=5000
SLIPPAGE_PCT=0.0005
```

---

## Key Design Decisions
- **Mock-first**: All Zerodha logic uses `MockKite` class with identical interface to real `KiteConnect`
- **Gemini as microservice**: Each Gemini call is isolated, stateless, with retry logic
- **DuckDB as single source of truth**: All data (candles, news, trades) queryable via SQL
- **Hard-coded kill switch**: Never AI-controlled, fixed ₹5,000 threshold

---

## Phase 2 PRD Implementation (March 2026)

### Completed Enhancements

#### 1. Multi-Factor Confluence Engine (`src/trading/signals.py`)
- **ConfluentSignalEngine**: Combines 200 EMA trend filter + RSI crossover + VWAP
- **SmartTrailingStop**: 3-stage stop management (Initial → Breakeven → 9 EMA trailing)
- **Time-based stop**: Tighten to 0.5 ATR if no target hit in 60 minutes
- **ATR-based position sizing**: `quantity = risk / (ATR × 1.5)`

#### 2. Historical Data Bootstrap (`src/storage/db.py`)
- `bootstrap_historical_data()`: Fetches 2 days of candles from Zerodha for 200 EMA calculation
- `aggregate_ticks_to_candles()`: Converts live ticks to OHLC candles
- Multi-interval support: 1min, 5min, 15min candles with proper indexing

#### 3. AI Audit Layer (`src/gemini/audit.py`)
- **TradeAuditor**: Unified visual + sentiment + technical analysis
- Gemini 2.0 Flash with specific system prompt for risk assessment
- Confidence threshold (0.8) gate before trade execution
- Rate limiting: 15 RPM with 4-second intervals

#### 4. Hybrid Kill Switch (`src/trading/risk.py`)
- **HybridKillSwitch**: Safety ceiling (3% from .env) + user-configurable limit
- System enforces `min(ceiling, user_limit)` - ceiling cannot be overridden
- `disable_trading_for_day()` method for full day lockout

#### 5. Independent Watchdog (`scripts/watchdog.py`)
- Runs separately from main engine
- Uses REST API (`kite.margins()`) - works even if WebSocket crashes
- Polls every 10 seconds, can kill main process and force-close positions

#### 6. Time-Gated Trading (`src/trading/scheduler.py`)
- **Observation Phase** (9:15-9:45): Data ingestion only
- **Active Trading** (9:45-14:45): Full trading enabled
- **Square-off Phase** (14:45-15:15): Exit all, no new entries
- **Post-Market** (15:30+): Generate daily Gemini report

#### 7. WebSocket Reconnection (`src/ingestion/real_kite.py`)
- Exponential backoff: 1s → 2s → 4s → ... → 60s max
- Auto-reconnect on disconnect with state tracking
- `ConnectionState` enum: DISCONNECTED, CONNECTING, CONNECTED, RECONNECTING, FAILED

#### 8. Frontend Components
- **AIPanel.jsx**: Sentiment gauge, confidence bar, confluence status, reasoning logs
- **TradingChart.jsx**: Lightweight-charts with 200/20/9 EMAs, VWAP, position markers
- **Heatmap.jsx**: RSI-colored grid with volume spike glow animation (>3x average)

#### 9. News TTL Cache (`src/ingestion/news_scraper.py`)
- Configurable TTL via `NEWS_CACHE_TTL` env var (default 120 seconds)
- Thread-safe caching with `get_cache_stats()` for monitoring

#### 10. Daily Report Generator (`src/gemini/autopsy.py`)
- `DailyReportGenerator`: Scheduled during POST_MARKET phase
- Saves both text report and JSON data to `reports/` directory
- Tracks win rate, best/worst trades, improvement suggestions

### New Files Created
```
src/trading/signals.py      - ConfluentSignalEngine + SmartTrailingStop
src/trading/scheduler.py    - TradingScheduler with time-gated phases
src/gemini/audit.py         - TradeAuditor for visual + sentiment analysis
scripts/watchdog.py         - Independent MTM monitor
frontend/src/components/AIPanel.jsx
frontend/src/components/TradingChart.jsx
frontend/src/components/Heatmap.jsx
.env.example                - Configuration template
```

### Configuration (.env)
```env
MTM_LOSS_CEILING=0.03           # 3% hard safety limit
NEWS_CACHE_TTL=120              # 2-minute news cache
WATCHDOG_POLL_INTERVAL=10       # 10-second watchdog check
RISK_PER_TRADE=500              # ₹500 risk per trade
```

### Chart Colors (Gemini Vision optimized)
- Background: #1a1a2e (deep navy)
- 200 EMA: #9d4edd (purple - trend)
- 20 EMA: #ff6b35 (orange)
- 9 EMA: #00f5d4 (cyan - trailing)
- VWAP: #4361ee (blue dashed)

---

## Security & Stability Audit (Mar 10, 2026)

### Critical Fixes Applied

| ID | Issue | File | Fix |
|----|-------|------|-----|
| **C1** | SSL verification disabled globally | `news_scraper.py` | Replaced global bypass with certifi-based secure SSL context |
| **C2** | Division by zero in autopsy | `autopsy.py` | Added zero-check guard for win rate calculation |

### High Priority Fixes Applied

| ID | Issue | File | Fix |
|----|-------|------|-----|
| **H3** | Stale `self.model` reference | `vision.py` | Updated to use `self.client.models.generate_content()` |
| **H4** | Race condition in news cache | `news_scraper.py` | Protected global cache with `_cache_lock` |
| **H5** | Silent WebSocket errors | `server.py` | Added logging and dead connection cleanup |
| **H6** | Method name mismatch | `server.py` | Fixed `close_trade` → `exit_by_ticker` |

### Medium Priority Fixes Applied

| ID | Issue | File | Fix |
|----|-------|------|-----|
| **M1** | `ENV_FILE` undefined before use | `server.py` | Moved definition to top of file |
| **M4** | CORS wildcard security | `server.py` | Made configurable via `ALLOWED_ORIGINS` env var |
| **M5** | No ticker input validation | `server.py` | Added `validate_ticker()` with regex pattern |
| **M6** | Thread-unsafe DB singleton | `db.py` | Added double-check locking with `threading.Lock` |

### AI Safety Fix

| ID | Issue | File | Fix |
|----|-------|------|-----|
| **A2** | No confidence threshold | `vision.py` | Added `min_confidence=0.6` parameter to `is_safe_to_enter()` |

### Low Priority Fix

| ID | Issue | File | Fix |
|----|-------|------|-----|
| **L1** | Deprecated `np.bool8` | `server.py` | Removed from type check |

### Verification
- ✅ All modified files compile successfully
- ✅ Core module imports verified
- ✅ No functionality removed

### Detailed Plan
See `plan.md` for full audit findings and remaining items.
