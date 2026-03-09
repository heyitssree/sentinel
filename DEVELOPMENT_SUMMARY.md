# Sentinel Trading System - Development Summary

**Last Updated:** March 9, 2026  
**Purpose:** Track development progress and enable session transfer

---

## Project Overview

**Sentinel** is an AI-powered paper trading system for Indian stocks (NSE) that uses:
- Real-time market data from Zerodha Kite API
- AI-driven technical analysis and sentiment analysis (Gemini)
- Paper trading with simulated portfolio
- React frontend dashboard

---

## Key Components

### Backend (`/Users/sree/sentinel/src/`)
| Component | File | Purpose |
|-----------|------|---------|
| API Server | `api/server.py` | FastAPI server, REST & WebSocket endpoints |
| Real Kite | `ingestion/real_kite.py` | Zerodha KiteConnect wrapper with SSL fix |
| Mock Kite | `ingestion/mock_kite.py` | Simulated market data for testing |
| News Scraper | `ingestion/news_scraper.py` | RSS feed scraper for stock news |
| Portfolio | `trading/portfolio.py` | Paper trading portfolio management |
| Sentiment | `gemini/sentiment.py` | AI sentiment analysis |
| Technical | `gemini/technical_analyst.py` | AI technical analysis |

### Frontend (`/Users/sree/sentinel/frontend/`)
- React + Vite + TailwindCSS
- Real-time WebSocket updates
- Stock watchlist, positions, trades, news panels

---

## Completed Features

### 1. Zerodha Kite API Integration
- **RealKite/RealTicker** classes mirror MockKite interface for easy swapping
- **SSL Certificate Fix** - Patched KiteConnect session to bypass macOS SSL issues:
  ```python
  def _patch_kite_session(kite: KiteConnect):
      original_request = kite.reqsession.request
      def patched_request(*args, **kwargs):
          kwargs['verify'] = False
          return original_request(*args, **kwargs)
      kite.reqsession.request = patched_request
  ```
- **Access Token Generation** - `/api/zerodha/generate-session` endpoint
- **Toggle Mock/Real** - `/api/market-data/toggle` endpoint

### 2. News System
- RSS feeds from Economic Times, Moneycontrol
- Per-ticker news fetching with caching
- Auto-refresh every 2 minutes in frontend
- Toggle between real RSS and mock news

### 3. Market Data Status
- `/api/market-data/status` - Shows current data source
- `/api/credentials/test/zerodha` - Tests Zerodha connection, shows actual Kite type

### 4. Bug Fixes Applied
- **JSON NaN Serialization** - `sanitize_floats()` helper prevents NaN/Inf JSON errors
- **News Caching** - Fixed `_seen_headlines` blocking re-fetches; clear on force refresh
- **Credentials Test** - Now shows actual RealKite/MockKite type instead of always "MockKite"

---

## Zerodha Credentials

| Key | Value | Notes |
|-----|-------|-------|
| API Key | `your_api_key` | In `.env` |
| API Secret | `your_api_secret` | In `.env` |
| Access Token | `your_access_token` | Generated, expires daily |
| User | Your Zerodha Client ID | |

### Re-authentication Flow
Access tokens expire daily. To re-authenticate:

1. Open: `https://kite.zerodha.com/connect/login?api_key=YOUR_API_KEY&v=3`
2. Login with Zerodha credentials
3. Copy `request_token` from redirect URL
4. Call: `curl -X POST "http://localhost:8000/api/zerodha/generate-session?request_token=YOUR_TOKEN"`

---

## API Endpoints

### Engine Control
```bash
# Start engine
curl -X POST http://localhost:8000/api/control -H "Content-Type: application/json" -d '{"action":"start"}'

# Stop engine
curl -X POST http://localhost:8000/api/control -H "Content-Type: application/json" -d '{"action":"stop"}'
```

### Market Data
```bash
# Check current source (mock/real)
curl http://localhost:8000/api/market-data/status

# Toggle between Mock and Real Kite (stop engine first)
curl -X POST http://localhost:8000/api/market-data/toggle

# Test Zerodha connection
curl -X POST http://localhost:8000/api/credentials/test/zerodha
```

### News
```bash
# Get news for ticker
curl http://localhost:8000/api/news/RELIANCE

# Force refresh news
curl -X POST http://localhost:8000/api/news/RELIANCE/refresh

# Toggle real/mock news
curl -X POST http://localhost:8000/api/news/toggle-source
```

### Status
```bash
# Full status with prices, portfolio, risk
curl http://localhost:8000/api/status

# Portfolio details
curl http://localhost:8000/api/portfolio

# Watchlist
curl http://localhost:8000/api/watchlist
```

---

## Running the Application

### Backend
```bash
cd /Users/sree/sentinel
source venv/bin/activate
python -m uvicorn src.api.server:app --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd /Users/sree/sentinel/frontend
npm run dev
```

Access at: **http://localhost:3000**

---

## Known Issues & Limitations

### 1. WebSocket Not Receiving Data
- **Status:** RealTicker shows `is_connected: false`
- **Cause:** Zerodha WebSocket connection not establishing properly
- **Workaround:** Use MockKite for testing; investigate WebSocket connection

### 2. Access Token Expiry
- Tokens expire daily at ~6 AM IST
- Must re-authenticate each trading day

### 3. Market Hours
- RealKite only streams data during NSE market hours (9:15 AM - 3:30 PM, Mon-Fri)
- Use MockKite outside market hours for testing

---

## Pending Tasks

1. **Fix RealTicker WebSocket** - Debug why `is_connected` stays false
2. **Add UI toggle** - Button to switch Mock/Real data in frontend
3. **Auto-reconnect** - Handle WebSocket disconnections gracefully
4. **Token refresh reminder** - Alert user when token expires

---

## File Changes Summary

### Modified Files
| File | Changes |
|------|---------|
| `src/api/server.py` | Added market-data endpoints, SSL fix imports, sanitize_floats, fixed credentials test |
| `src/ingestion/real_kite.py` | Created RealKite/RealTicker, SSL patch, instrument tokens |
| `src/ingestion/news_scraper.py` | Fixed caching, clear seen_headlines on force refresh |
| `frontend/src/App.jsx` | Added NewsPanel auto-refresh (2 min interval) |
| `.env` | Added KITE_ACCESS_TOKEN |

### New Files
| File | Purpose |
|------|---------|
| `src/ingestion/real_kite.py` | Real Zerodha Kite integration |
| `DEVELOPMENT_SUMMARY.md` | This file |

---

## Watchlist Stocks

RELIANCE, ICICIBANK, TCS, HDFCBANK, HINDUNILVR, SBIN, BHARTIARTL, KOTAKBANK, ITC, JSWSTEEL, INFY, TATAMOTORS, WIPRO, HCLTECH, MARUTI, AXISBANK, SUNPHARMA, TITAN, BAJFINANCE, ADANIENT

---

## Architecture Notes

### Data Flow
```
Zerodha WebSocket → RealTicker → SentinelEngine → WebSocket → Frontend
                         ↓
                   Price Updates → Portfolio → Indicators → Signals
                                                    ↓
                                              AI Analysis (Gemini)
                                                    ↓
                                              Trade Execution (Paper)
```

### Trading Logic
1. Ticker streams prices via WebSocket
2. Every 10 seconds, engine analyzes each stock
3. Calculates RSI, VWAP, EMA indicators
4. Checks entry/exit signals
5. For entry: runs sentiment + technical AI analysis
6. Executes paper trade if all checks pass
7. Monitors positions for take-profit (2%) / stop-loss (1%)

---

## Session Transfer Notes

When continuing development:
1. Check if access token is valid (test Zerodha endpoint)
2. If expired, re-authenticate via login flow
3. Start backend, then frontend
4. Use MockKite if market is closed
5. Check `/api/market-data/status` to verify data source
