# Sentinel Trading Platform - Setup Guide

A real-time algorithmic trading platform for NSE (National Stock Exchange of India) with AI-powered analysis using Google Gemini.

## Prerequisites

- **Python 3.10+** (Anaconda recommended)
- **Node.js 18+** (for frontend)
- **Zerodha Kite Connect** account with API access
- **Google Gemini API** key (optional, for AI sentiment analysis)

## Quick Start

### 1. Clone and Setup Environment

```bash
# Clone the repository
git clone https://github.com/yourusername/sentinel.git
cd sentinel

# Create Python virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your credentials
nano .env  # or use any text editor
```

**Required credentials:**

| Variable | Description | How to get |
|----------|-------------|------------|
| `KITE_API_KEY` | Zerodha Kite API key | [Kite Connect Developer Console](https://developers.kite.trade/) |
| `KITE_API_SECRET` | Zerodha Kite API secret | Same as above |
| `KITE_ACCESS_TOKEN` | Daily access token | OAuth flow (see below) |
| `GEMINI_API_KEY` | Google Gemini API key | [Google AI Studio](https://makersuite.google.com/app/apikey) |

### 3. Setup Portfolio Data

```bash
# Copy example portfolio file
cp data/portfolio.json.example data/portfolio.json

# Edit starting capital and watchlist as needed
nano data/portfolio.json
```

### 4. Setup Frontend

```bash
cd frontend

# Install Node dependencies
npm install

# Start development server
npm run dev
```

### 5. Start Backend Server

```bash
# In project root (with venv activated)
python -m src.api.server
```

The API will be available at `http://localhost:8000`
The frontend will be available at `http://localhost:3000` (or 3001/3002)

---

## Zerodha Kite Access Token

The access token expires daily and must be refreshed via OAuth flow:

### Option 1: Manual Login (Recommended for Development)

1. Go to Kite Connect login URL:
   ```
   https://kite.zerodha.com/connect/login?v=3&api_key=YOUR_API_KEY
   ```

2. Login with your Zerodha credentials

3. After redirect, copy the `request_token` from URL

4. Exchange for access token:
   ```bash
   curl -X POST "https://api.kite.trade/session/token" \
     -d "api_key=YOUR_API_KEY" \
     -d "request_token=YOUR_REQUEST_TOKEN" \
     -d "checksum=SHA256(api_key + request_token + api_secret)"
   ```

5. Update `KITE_ACCESS_TOKEN` in `.env`

### Option 2: Use the Dashboard

1. Start the server without access token
2. Open frontend dashboard
3. Go to Settings → API Credentials
4. Follow the OAuth flow in the UI

---

## Configuration Reference

### Risk Management Settings

```env
# Maximum loss before kill switch triggers (3% of capital)
MTM_LOSS_CEILING=0.03

# Starting capital for calculations
STARTING_CAPITAL=100000

# Risk per trade in INR
RISK_PER_TRADE=500
```

### Trading Schedule (IST)

```env
OBSERVATION_START=09:15    # Market opens, observation phase
OBSERVATION_END=09:45      # Active trading begins
ACTIVE_TRADING_END=14:45   # Stop new entries
SQUARE_OFF_END=15:15       # Close all positions
POST_MARKET_START=15:30    # Market closes
```

### News Scraper

```env
# Cache TTL for RSS feeds (seconds)
NEWS_CACHE_TTL=120
```

---

## Project Structure

```
sentinel/
├── src/
│   ├── api/           # FastAPI backend server
│   ├── gemini/        # AI modules (sentiment, autopsy, vision)
│   ├── ingestion/     # Market data & news scrapers
│   ├── storage/       # DuckDB database layer
│   └── trading/       # Signal engine, risk management
├── frontend/          # React dashboard
├── config/            # Configuration files
├── data/              # Database & portfolio (gitignored)
├── charts/            # Generated chart images (gitignored)
└── logs/              # Log files (gitignored)
```

---

## Features

### Trading Engine
- Real-time market data via Zerodha Kite WebSocket
- Technical indicators: VWAP, EMA (9, 20, 200), RSI
- Confluence-based signal generation
- Paper trading mode (no real orders)

### AI Analysis (Gemini)
- News sentiment analysis for Nifty 50 stocks
- Daily post-trade autopsy reports
- Technical chart pattern recognition

### Dashboard
- Real-time heatmap of Nifty 50
- TradingView-style candlestick charts
- AI reasoning panel with live sentiment
- Risk management controls

### Safety Features
- MTM loss kill switch (hard-coded ceiling)
- Rate limiting on orders
- Market hours enforcement
- Independent watchdog process

---

## Troubleshooting

### "Access token expired"
Refresh the access token via OAuth flow (see above).

### "Gemini model not found"
The platform uses `gemini-2.5-flash`. Ensure your API key has access to this model.

### "No news data"
News is fetched from RSS feeds. Check your internet connection and wait for the 5-minute refresh cycle.

### Database errors
Delete `data/sentinel.duckdb*` files to reset the database.

---

## Development

### Running Tests
```bash
pytest tests/
```

### Code Style
```bash
# Format code
black src/

# Lint
flake8 src/
```

### Building Frontend for Production
```bash
cd frontend
npm run build
```

---

## Disclaimer

⚠️ **This is for educational purposes only.** 

- Paper trading mode is enabled by default
- Always test thoroughly before enabling live trading
- The authors are not responsible for any financial losses
- Past performance does not guarantee future results

---

## License

MIT License - See LICENSE file for details.
