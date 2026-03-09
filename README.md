# 🛡️ The Sentinel: Multimodal Alpha Engine

A high-availability paper trading pipeline that treats Gemini 2.0 Flash as an "Inference Microservice" for sentiment-weighted, vision-audited trade decisions.

## 🏗️ Architecture

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

## ✨ Features

### Feature A: Vibe-Weighted Entry
- Analyzes last 10 headlines before trade entry
- Sentiment score from -1 to 1
- Blocks trades on negative sentiment

### Feature B: Visual Auditor (Gemini Vision)
- Generates candlestick charts with indicators
- Detects patterns (Cup & Handle, Breakout, etc.)
- Prevents "buying the top" of vertical spikes

### Feature C: Post-Trade Autopsy
- Daily review at market close
- Analyzes winning vs losing trades
- Provides stop-loss optimization suggestions

## 🚀 Quick Start

> **📖 See [SETUP.md](SETUP.md) for detailed installation instructions.**

### 1. Setup Environment

```bash
git clone https://github.com/yourusername/sentinel.git
cd sentinel
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Credentials

```bash
cp .env.example .env
# Edit .env with your Zerodha and Gemini API keys
```

### 3. Setup Frontend

```bash
cd frontend
npm install
npm run dev
```

### 4. Start Backend

```bash
python -m src.api.server
```

Open `http://localhost:3000` for the dashboard.

## 📁 Project Structure

```
sentinel/
├── config/
│   └── settings.py          # Configuration & constants
├── data/
│   └── sentinel.duckdb      # Time-series database
├── src/
│   ├── ingestion/
│   │   ├── mock_kite.py     # Mock Zerodha WebSocket
│   │   └── news_scraper.py  # RSS feed parser
│   ├── storage/
│   │   └── db.py            # DuckDB operations
│   ├── signals/
│   │   └── indicators.py    # VWAP, RSI, EMA
│   ├── gemini/
│   │   ├── sentiment.py     # News sentiment analysis
│   │   ├── vision.py        # Chart pattern detection
│   │   └── autopsy.py       # Post-trade review
│   ├── trading/
│   │   ├── executor.py      # Paper trade execution
│   │   └── risk.py          # Kill switch, rate limiter
│   └── charts/
│       └── generator.py     # Matplotlib chart generation
├── main.py                   # Heartbeat orchestrator
├── requirements.txt
└── README.md
```

## 📊 Trading Logic

### Entry Conditions
All three must be true:
1. **Price > VWAP** (intraday strength)
2. **RSI > 60** (bullish momentum)
3. **Price > EMA(20)** (trend confirmation)

### Gemini Gates
After technical signal, two AI gates:
1. **Sentiment Gate**: Score > 0 required
2. **Vision Gate**: "SAFE" assessment required

### Risk Controls
- **Kill Switch**: Hard-coded ₹5,000 MTM loss limit
- **Rate Limiter**: 10 orders per second (SEBI 2026)
- **Market Hours**: 9:15 AM - 3:30 PM IST only

## 🛡️ Compliance (SEBI 2026)

- ✅ **10 OPS Limit**: Rate limiter enforced
- ✅ **Personal Use**: Single client ID
- ✅ **Kill Switch**: Hard-coded, never AI-controlled

## 📈 Watchlist

Default high-liquidity stocks:
- RELIANCE
- ICICIBANK
- TCS
- INFY
- HDFCBANK

Edit `config/settings.py` to modify.

## 🔧 Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MTM_LOSS_LIMIT` | ₹5,000 | Kill switch threshold |
| `SLIPPAGE_PCT` | 0.05% | Simulated slippage |
| `RSI_ENTRY_THRESHOLD` | 60 | RSI minimum for entry |
| `EMA_PERIOD` | 20 | EMA lookback period |
| `CANDLE_INTERVAL_SECONDS` | 300 | 5-minute candles |

## 🧪 Testing

```bash
# Run quick test (one heartbeat cycle)
python main.py --mock --test

# Check database
python -c "from src.storage.db import get_db; db = get_db(); print(db.get_all_positions())"
```

## 📋 Logs & Reports

- **Live Logs**: `sentinel.log`
- **Autopsy Reports**: `reports/autopsy_YYYYMMDD.txt`
- **Charts**: `charts/TICKER_TIMEFRAME_TIMESTAMP.png`

## ⚠️ Disclaimer

This is a **paper trading** system for educational purposes. No real money is at risk. The mock Kite class simulates order execution with realistic slippage.

Before using with real APIs:
1. Replace `MockKite` with real `KiteConnect`
2. Obtain Zerodha API subscription
3. Thoroughly backtest strategies
4. Start with minimal capital

## 🔄 Swapping to Real Trading

The system is designed for easy transition:

```python
# In main.py, replace:
from src.ingestion.mock_kite import MockKite, MockTicker

# With:
from kiteconnect import KiteConnect, KiteTicker
```

The interface is identical - just swap the imports.

---

Built with ❤️ for smarter, AI-augmented trading decisions.
