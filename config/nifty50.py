"""
Nifty 50 Configuration for The Sentinel.
Full list of Nifty 50 stocks with sector mapping and NSE instrument tokens.
Used for the Technical Heatmap and market-wide context analysis.
"""
from typing import Dict, List
from dataclasses import dataclass


@dataclass
class Stock:
    """Represents a Nifty 50 stock."""
    ticker: str
    name: str
    sector: str
    instrument_token: int
    weight: float = 0.0  # Index weight percentage


# Nifty 50 Sectors
SECTORS = [
    "Banking",
    "IT",
    "Oil & Gas",
    "FMCG",
    "Automobile",
    "Pharma",
    "Metals",
    "Financial Services",
    "Telecom",
    "Power",
    "Cement",
    "Consumer Durables",
    "Diversified",
]

# Full Nifty 50 Stock List with NSE Instrument Tokens
# Tokens are from Zerodha's instrument master
NIFTY_50: Dict[str, Stock] = {
    # Banking (Major Weight)
    "HDFCBANK": Stock("HDFCBANK", "HDFC Bank Ltd", "Banking", 341249, 13.5),
    "ICICIBANK": Stock("ICICIBANK", "ICICI Bank Ltd", "Banking", 1270529, 7.8),
    "KOTAKBANK": Stock("KOTAKBANK", "Kotak Mahindra Bank", "Banking", 492033, 4.2),
    "AXISBANK": Stock("AXISBANK", "Axis Bank Ltd", "Banking", 1510401, 3.1),
    "SBIN": Stock("SBIN", "State Bank of India", "Banking", 779521, 3.0),
    "INDUSINDBK": Stock("INDUSINDBK", "IndusInd Bank Ltd", "Banking", 1346049, 1.2),
    
    # IT Services
    "TCS": Stock("TCS", "Tata Consultancy Services", "IT", 2953217, 4.2),
    "INFY": Stock("INFY", "Infosys Ltd", "IT", 408065, 6.5),
    "HCLTECH": Stock("HCLTECH", "HCL Technologies Ltd", "IT", 1850625, 1.8),
    "WIPRO": Stock("WIPRO", "Wipro Ltd", "IT", 969473, 1.0),
    "TECHM": Stock("TECHM", "Tech Mahindra Ltd", "IT", 3465729, 0.9),
    "LTIM": Stock("LTIM", "LTIMindtree Ltd", "IT", 4561409, 0.8),
    
    # Oil & Gas
    "RELIANCE": Stock("RELIANCE", "Reliance Industries Ltd", "Oil & Gas", 738561, 10.5),
    "ONGC": Stock("ONGC", "Oil & Natural Gas Corp", "Oil & Gas", 633601, 1.2),
    "BPCL": Stock("BPCL", "Bharat Petroleum Corp", "Oil & Gas", 134657, 0.6),
    
    # FMCG
    "HINDUNILVR": Stock("HINDUNILVR", "Hindustan Unilever Ltd", "FMCG", 356865, 2.8),
    "ITC": Stock("ITC", "ITC Ltd", "FMCG", 424961, 4.5),
    "NESTLEIND": Stock("NESTLEIND", "Nestle India Ltd", "FMCG", 4598529, 0.9),
    "BRITANNIA": Stock("BRITANNIA", "Britannia Industries Ltd", "FMCG", 140033, 0.6),
    "TATACONSUM": Stock("TATACONSUM", "Tata Consumer Products", "FMCG", 3506433, 0.6),
    
    # Automobile
    "MARUTI": Stock("MARUTI", "Maruti Suzuki India Ltd", "Automobile", 2815745, 1.8),
    "TATAMOTORS": Stock("TATAMOTORS", "Tata Motors Ltd", "Automobile", 884737, 1.5),
    "M&M": Stock("M&M", "Mahindra & Mahindra Ltd", "Automobile", 519937, 2.0),
    "BAJAJ-AUTO": Stock("BAJAJ-AUTO", "Bajaj Auto Ltd", "Automobile", 4267265, 0.8),
    "EICHERMOT": Stock("EICHERMOT", "Eicher Motors Ltd", "Automobile", 232961, 0.7),
    "HEROMOTOCO": Stock("HEROMOTOCO", "Hero MotoCorp Ltd", "Automobile", 345089, 0.5),
    
    # Pharma & Healthcare
    "SUNPHARMA": Stock("SUNPHARMA", "Sun Pharmaceutical Ind", "Pharma", 857857, 1.5),
    "DRREDDY": Stock("DRREDDY", "Dr. Reddy's Laboratories", "Pharma", 225537, 0.8),
    "CIPLA": Stock("CIPLA", "Cipla Ltd", "Pharma", 177665, 0.8),
    "DIVISLAB": Stock("DIVISLAB", "Divi's Laboratories Ltd", "Pharma", 2800641, 0.6),
    "APOLLOHOSP": Stock("APOLLOHOSP", "Apollo Hospitals Enterprise", "Pharma", 40193, 0.7),
    
    # Metals & Mining
    "TATASTEEL": Stock("TATASTEEL", "Tata Steel Ltd", "Metals", 895745, 1.2),
    "JSWSTEEL": Stock("JSWSTEEL", "JSW Steel Ltd", "Metals", 3001089, 0.9),
    "HINDALCO": Stock("HINDALCO", "Hindalco Industries Ltd", "Metals", 348929, 0.8),
    "COALINDIA": Stock("COALINDIA", "Coal India Ltd", "Metals", 5215745, 0.7),
    
    # Financial Services (Non-Banking)
    "BAJFINANCE": Stock("BAJFINANCE", "Bajaj Finance Ltd", "Financial Services", 81153, 2.5),
    "BAJAJFINSV": Stock("BAJAJFINSV", "Bajaj Finserv Ltd", "Financial Services", 4268801, 0.8),
    "HDFCLIFE": Stock("HDFCLIFE", "HDFC Life Insurance Co", "Financial Services", 467969, 0.7),
    "SBILIFE": Stock("SBILIFE", "SBI Life Insurance Co", "Financial Services", 5765377, 0.6),
    
    # Telecom
    "BHARTIARTL": Stock("BHARTIARTL", "Bharti Airtel Ltd", "Telecom", 2714625, 3.5),
    
    # Power & Utilities
    "POWERGRID": Stock("POWERGRID", "Power Grid Corp of India", "Power", 3834113, 0.8),
    "NTPC": Stock("NTPC", "NTPC Ltd", "Power", 2977281, 1.0),
    "ADANIPORTS": Stock("ADANIPORTS", "Adani Ports & SEZ Ltd", "Power", 3861249, 1.2),
    
    # Cement & Construction
    "ULTRACEMCO": Stock("ULTRACEMCO", "UltraTech Cement Ltd", "Cement", 2952193, 1.2),
    "GRASIM": Stock("GRASIM", "Grasim Industries Ltd", "Cement", 315393, 0.9),
    "SHRIRAMFIN": Stock("SHRIRAMFIN", "Shriram Finance Ltd", "Financial Services", 1102337, 0.5),
    
    # Consumer Durables
    "TITAN": Stock("TITAN", "Titan Company Ltd", "Consumer Durables", 897537, 1.5),
    
    # Diversified / Conglomerates
    "LT": Stock("LT", "Larsen & Toubro Ltd", "Diversified", 2939649, 3.8),
    "ADANIENT": Stock("ADANIENT", "Adani Enterprises Ltd", "Diversified", 6401, 1.0),
    "ASIANPAINT": Stock("ASIANPAINT", "Asian Paints Ltd", "Consumer Durables", 60417, 1.5),
}

# Convenience lists
NIFTY_50_TICKERS: List[str] = list(NIFTY_50.keys())

# Instrument token to ticker mapping
TOKEN_TO_TICKER: Dict[int, str] = {
    stock.instrument_token: ticker for ticker, stock in NIFTY_50.items()
}

# Ticker to instrument token mapping
TICKER_TO_TOKEN: Dict[str, int] = {
    ticker: stock.instrument_token for ticker, stock in NIFTY_50.items()
}

# Group stocks by sector
STOCKS_BY_SECTOR: Dict[str, List[str]] = {}
for ticker, stock in NIFTY_50.items():
    if stock.sector not in STOCKS_BY_SECTOR:
        STOCKS_BY_SECTOR[stock.sector] = []
    STOCKS_BY_SECTOR[stock.sector].append(ticker)

# Sector order for display (by importance/weight)
SECTOR_ORDER = [
    "Banking",
    "IT",
    "Oil & Gas",
    "Financial Services",
    "FMCG",
    "Automobile",
    "Pharma",
    "Metals",
    "Telecom",
    "Power",
    "Cement",
    "Consumer Durables",
    "Diversified",
]


def get_stock(ticker: str) -> Stock:
    """Get stock details by ticker."""
    return NIFTY_50.get(ticker)


def get_sector_stocks(sector: str) -> List[str]:
    """Get all tickers in a sector."""
    return STOCKS_BY_SECTOR.get(sector, [])


def get_all_tokens() -> List[int]:
    """Get all instrument tokens for WebSocket subscription."""
    return [stock.instrument_token for stock in NIFTY_50.values()]


def get_top_weighted(n: int = 10) -> List[str]:
    """Get top N stocks by index weight."""
    sorted_stocks = sorted(
        NIFTY_50.items(),
        key=lambda x: x[1].weight,
        reverse=True
    )
    return [ticker for ticker, _ in sorted_stocks[:n]]
