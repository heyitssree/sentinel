"""
Paper Trading Portfolio Manager.
Manages virtual funds, holdings, and P&L tracking.

Includes:
- ATR-based position sizing (1.5 ATR = stop loss distance)
- Dynamic watchlist presets (Nifty 50, Bank Nifty, Custom)
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import json
from pathlib import Path

logger = logging.getLogger(__name__)


# Watchlist presets
NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
    "HINDUNILVR", "SBIN", "BHARTIARTL", "KOTAKBANK", "ITC",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "SUNPHARMA",
    "TITAN", "ULTRACEMCO", "BAJFINANCE", "WIPRO", "HCLTECH",
    "ONGC", "NTPC", "POWERGRID", "TATASTEEL", "JSWSTEEL",
    "ADANIENT", "ADANIPORTS", "BAJAJ-AUTO", "BAJAJFINSV", "BPCL",
    "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY",
    "EICHERMOT", "GRASIM", "HDFCLIFE", "HEROMOTOCO", "HINDALCO",
    "INDUSINDBK", "M&M", "NESTLEIND", "SBILIFE", "SHREECEM",
    "TATACONSUM", "TATAMOTORS", "TECHM", "APOLLOHOSP", "UPL"
]

BANK_NIFTY = [
    "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN",
    "INDUSINDBK", "BANDHANBNK", "FEDERALBNK", "IDFCFIRSTB", "PNB",
    "AUBANK", "BANKBARODA"
]

WATCHLIST_PRESETS = {
    "nifty_50": NIFTY_50,
    "bank_nifty": BANK_NIFTY,
    "default": ["RELIANCE", "ICICIBANK", "TCS", "INFY", "HDFCBANK"],
}


@dataclass
class Holding:
    """Represents a stock holding."""
    ticker: str
    quantity: int
    avg_price: float
    current_price: float = 0.0
    
    @property
    def invested_value(self) -> float:
        return self.quantity * self.avg_price
    
    @property
    def current_value(self) -> float:
        return self.quantity * self.current_price
    
    @property
    def pnl(self) -> float:
        return self.current_value - self.invested_value
    
    @property
    def pnl_percent(self) -> float:
        if self.invested_value == 0:
            return 0.0
        return (self.pnl / self.invested_value) * 100
    
    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "quantity": self.quantity,
            "avg_price": self.avg_price,
            "current_price": self.current_price,
            "invested_value": self.invested_value,
            "current_value": self.current_value,
            "pnl": self.pnl,
            "pnl_percent": self.pnl_percent
        }


@dataclass
class Portfolio:
    """Paper trading portfolio."""
    starting_capital: float = 100000.0  # ₹1 Lakh default
    available_cash: float = 100000.0
    holdings: Dict[str, Holding] = field(default_factory=dict)
    watchlist: List[str] = field(default_factory=list)
    realized_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    
    @property
    def holdings_value(self) -> float:
        return sum(h.current_value for h in self.holdings.values())
    
    @property
    def total_value(self) -> float:
        return self.available_cash + self.holdings_value
    
    @property
    def unrealized_pnl(self) -> float:
        return sum(h.pnl for h in self.holdings.values())
    
    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl
    
    @property
    def total_pnl_percent(self) -> float:
        if self.starting_capital == 0:
            return 0.0
        return ((self.total_value - self.starting_capital) / self.starting_capital) * 100
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    def to_dict(self) -> dict:
        return {
            "starting_capital": self.starting_capital,
            "available_cash": self.available_cash,
            "holdings_value": self.holdings_value,
            "total_value": self.total_value,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_pnl": self.total_pnl,
            "total_pnl_percent": self.total_pnl_percent,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "win_rate": self.win_rate,
            "holdings": {k: v.to_dict() for k, v in self.holdings.items()},
            "watchlist": self.watchlist
        }


class PortfolioManager:
    """
    Manages paper trading portfolio with funds and holdings.
    """
    
    # Available stocks for paper trading (NSE large caps)
    AVAILABLE_STOCKS = [
        "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
        "HINDUNILVR", "SBIN", "BHARTIARTL", "KOTAKBANK", "ITC",
        "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "SUNPHARMA",
        "TITAN", "ULTRACEMCO", "BAJFINANCE", "WIPRO", "HCLTECH",
        "ONGC", "NTPC", "POWERGRID", "TATASTEEL", "JSWSTEEL"
    ]
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.portfolio_file = self.data_dir / "portfolio.json"
        self.portfolio = self._load_portfolio()
        logger.info(f"Portfolio loaded: ₹{self.portfolio.total_value:,.2f}")
    
    def _load_portfolio(self) -> Portfolio:
        """Load portfolio from file or create new."""
        if self.portfolio_file.exists():
            try:
                data = json.loads(self.portfolio_file.read_text())
                portfolio = Portfolio(
                    starting_capital=data.get("starting_capital", 100000.0),
                    available_cash=data.get("available_cash", 100000.0),
                    watchlist=data.get("watchlist", ["RELIANCE", "ICICIBANK", "TCS", "INFY", "HDFCBANK"]),
                    realized_pnl=data.get("realized_pnl", 0.0),
                    total_trades=data.get("total_trades", 0),
                    winning_trades=data.get("winning_trades", 0)
                )
                
                # Restore holdings
                for ticker, h_data in data.get("holdings", {}).items():
                    portfolio.holdings[ticker] = Holding(
                        ticker=h_data["ticker"],
                        quantity=h_data["quantity"],
                        avg_price=h_data["avg_price"],
                        current_price=h_data.get("current_price", h_data["avg_price"])
                    )
                
                return portfolio
            except Exception as e:
                logger.warning(f"Error loading portfolio: {e}, creating new")
        
        # Default portfolio with 5 stocks
        return Portfolio(
            watchlist=["RELIANCE", "ICICIBANK", "TCS", "INFY", "HDFCBANK"]
        )
    
    def _save_portfolio(self):
        """Save portfolio to file."""
        data = {
            "starting_capital": self.portfolio.starting_capital,
            "available_cash": self.portfolio.available_cash,
            "watchlist": self.portfolio.watchlist,
            "realized_pnl": self.portfolio.realized_pnl,
            "total_trades": self.portfolio.total_trades,
            "winning_trades": self.portfolio.winning_trades,
            "holdings": {k: {
                "ticker": v.ticker,
                "quantity": v.quantity,
                "avg_price": v.avg_price,
                "current_price": v.current_price
            } for k, v in self.portfolio.holdings.items()}
        }
        self.portfolio_file.write_text(json.dumps(data, indent=2))
    
    def set_capital(self, amount: float) -> bool:
        """Set starting capital (resets portfolio)."""
        if amount < 10000:
            logger.warning("Minimum capital is ₹10,000")
            return False
        
        self.portfolio = Portfolio(
            starting_capital=amount,
            available_cash=amount,
            watchlist=self.portfolio.watchlist  # Keep watchlist
        )
        self._save_portfolio()
        logger.info(f"Capital set to ₹{amount:,.2f}")
        return True
    
    def reset_portfolio(self):
        """Reset portfolio to starting capital."""
        capital = self.portfolio.starting_capital
        watchlist = self.portfolio.watchlist
        self.portfolio = Portfolio(
            starting_capital=capital,
            available_cash=capital,
            watchlist=watchlist
        )
        self._save_portfolio()
        logger.info("Portfolio reset")
    
    def add_to_watchlist(self, ticker: str) -> bool:
        """Add stock to watchlist."""
        ticker = ticker.upper()
        
        if ticker not in self.AVAILABLE_STOCKS:
            logger.warning(f"{ticker} not in available stocks")
            return False
        
        if ticker in self.portfolio.watchlist:
            logger.warning(f"{ticker} already in watchlist")
            return False
        
        if len(self.portfolio.watchlist) >= 10:
            logger.warning("Maximum 10 stocks in watchlist")
            return False
        
        self.portfolio.watchlist.append(ticker)
        self._save_portfolio()
        logger.info(f"Added {ticker} to watchlist")
        return True
    
    def remove_from_watchlist(self, ticker: str) -> bool:
        """Remove stock from watchlist."""
        ticker = ticker.upper()
        
        if ticker not in self.portfolio.watchlist:
            logger.warning(f"{ticker} not in watchlist")
            return False
        
        if ticker in self.portfolio.holdings:
            logger.warning(f"Cannot remove {ticker} - has open position")
            return False
        
        if len(self.portfolio.watchlist) <= 1:
            logger.warning("Must have at least 1 stock in watchlist")
            return False
        
        self.portfolio.watchlist.remove(ticker)
        self._save_portfolio()
        logger.info(f"Removed {ticker} from watchlist")
        return True
    
    def can_buy(self, ticker: str, quantity: int, price: float) -> tuple[bool, str]:
        """Check if buy order is allowed."""
        cost = quantity * price
        
        if ticker not in self.portfolio.watchlist:
            return False, f"{ticker} not in watchlist"
        
        if cost > self.portfolio.available_cash:
            return False, f"Insufficient funds. Need ₹{cost:,.2f}, have ₹{self.portfolio.available_cash:,.2f}"
        
        return True, "OK"
    
    def execute_buy(self, ticker: str, quantity: int, price: float) -> bool:
        """Execute buy order."""
        can, reason = self.can_buy(ticker, quantity, price)
        if not can:
            logger.warning(f"Buy rejected: {reason}")
            return False
        
        cost = quantity * price
        
        if ticker in self.portfolio.holdings:
            # Average down/up
            holding = self.portfolio.holdings[ticker]
            total_qty = holding.quantity + quantity
            total_cost = (holding.quantity * holding.avg_price) + cost
            holding.quantity = total_qty
            holding.avg_price = total_cost / total_qty
            holding.current_price = price
        else:
            # New position
            self.portfolio.holdings[ticker] = Holding(
                ticker=ticker,
                quantity=quantity,
                avg_price=price,
                current_price=price
            )
        
        self.portfolio.available_cash -= cost
        self._save_portfolio()
        logger.info(f"BUY {quantity} {ticker} @ ₹{price:.2f} = ₹{cost:,.2f}")
        return True
    
    def execute_sell(self, ticker: str, quantity: int, price: float) -> tuple[bool, float]:
        """Execute sell order. Returns (success, realized_pnl)."""
        if ticker not in self.portfolio.holdings:
            logger.warning(f"No holding for {ticker}")
            return False, 0.0
        
        holding = self.portfolio.holdings[ticker]
        
        if quantity > holding.quantity:
            logger.warning(f"Insufficient quantity. Have {holding.quantity}, selling {quantity}")
            return False, 0.0
        
        # Calculate P&L
        sell_value = quantity * price
        cost_basis = quantity * holding.avg_price
        pnl = sell_value - cost_basis
        
        # Update holding
        holding.quantity -= quantity
        holding.current_price = price
        
        if holding.quantity == 0:
            del self.portfolio.holdings[ticker]
        
        # Update portfolio
        self.portfolio.available_cash += sell_value
        self.portfolio.realized_pnl += pnl
        self.portfolio.total_trades += 1
        if pnl > 0:
            self.portfolio.winning_trades += 1
        
        self._save_portfolio()
        logger.info(f"SELL {quantity} {ticker} @ ₹{price:.2f} = ₹{sell_value:,.2f}, PnL: ₹{pnl:,.2f}")
        return True, pnl
    
    def update_prices(self, prices: Dict[str, float]):
        """Update current prices for holdings."""
        for ticker, price in prices.items():
            if ticker in self.portfolio.holdings:
                self.portfolio.holdings[ticker].current_price = price
    
    def get_portfolio(self) -> dict:
        """Get portfolio summary."""
        return self.portfolio.to_dict()
    
    def get_holdings(self) -> List[dict]:
        """Get all holdings."""
        return [h.to_dict() for h in self.portfolio.holdings.values()]
    
    def get_watchlist(self) -> List[str]:
        """Get watchlist."""
        return self.portfolio.watchlist
    
    def get_available_stocks(self) -> List[str]:
        """Get stocks available to add to watchlist."""
        return [s for s in self.AVAILABLE_STOCKS if s not in self.portfolio.watchlist]
    
    def set_watchlist_preset(self, preset_name: str) -> bool:
        """
        Switch to a watchlist preset (hot-swap, no restart needed).
        
        Args:
            preset_name: One of 'nifty_50', 'bank_nifty', 'default', or 'custom'
            
        Returns:
            True if preset was applied
        """
        preset_name = preset_name.lower()
        
        if preset_name == "custom":
            logger.info("Keeping custom watchlist")
            return True
        
        if preset_name not in WATCHLIST_PRESETS:
            logger.warning(f"Unknown preset: {preset_name}")
            return False
        
        # Check for open positions
        open_positions = set(self.portfolio.holdings.keys())
        new_watchlist = WATCHLIST_PRESETS[preset_name]
        
        if open_positions - set(new_watchlist):
            logger.warning(
                f"Cannot switch to {preset_name}: open positions in stocks not in new watchlist"
            )
            return False
        
        self.portfolio.watchlist = list(new_watchlist)
        self._save_portfolio()
        logger.info(f"Switched to {preset_name} watchlist ({len(new_watchlist)} stocks)")
        return True
    
    def get_watchlist_presets(self) -> Dict[str, int]:
        """Get available watchlist presets and their stock counts."""
        return {name: len(stocks) for name, stocks in WATCHLIST_PRESETS.items()}
    
    @staticmethod
    def calculate_quantity(
        total_capital: float,
        risk_per_trade: float,
        atr: float,
        atr_multiplier: float = 1.5,
        price: float = None,
        max_position_pct: float = 0.1
    ) -> Tuple[int, float]:
        """
        Calculate position size based on ATR risk management.
        
        Formula: quantity = risk_amount / (ATR * multiplier)
        Where ATR * multiplier = stop loss distance
        
        Args:
            total_capital: Total portfolio value
            risk_per_trade: Risk amount in INR (e.g., 500) or as decimal (e.g., 0.005)
            atr: Current ATR value for the stock
            atr_multiplier: Multiplier for stop loss distance (default 1.5)
            price: Current stock price (for max position check)
            max_position_pct: Maximum position size as % of capital (default 10%)
            
        Returns:
            Tuple of (quantity, stop_loss_distance)
        """
        if atr <= 0:
            logger.warning("ATR is zero or negative, using minimum quantity of 1")
            return 1, 0.0
        
        # Convert risk_per_trade to absolute value if decimal
        if risk_per_trade < 1:
            risk_amount = total_capital * risk_per_trade
        else:
            risk_amount = risk_per_trade
        
        # Stop loss distance = ATR * multiplier
        stop_loss_dist = atr * atr_multiplier
        
        # Quantity = Risk / Stop Loss Distance
        quantity = int(risk_amount / stop_loss_dist)
        
        # Ensure at least 1 share
        quantity = max(1, quantity)
        
        # Check maximum position size if price provided
        if price and price > 0:
            max_qty = int((total_capital * max_position_pct) / price)
            if quantity > max_qty:
                logger.info(f"Position size capped: {quantity} -> {max_qty} (max {max_position_pct*100}% rule)")
                quantity = max(1, max_qty)
        
        logger.debug(
            f"ATR Position Size: risk=₹{risk_amount:.0f}, ATR={atr:.2f}, "
            f"SL dist={stop_loss_dist:.2f}, qty={quantity}"
        )
        
        return quantity, stop_loss_dist
    
    def calculate_trade_quantity(
        self,
        atr: float,
        price: float,
        risk_per_trade: float = 500.0
    ) -> Tuple[int, float, float]:
        """
        Calculate trade quantity using portfolio capital.
        
        Args:
            atr: Current ATR for the stock
            price: Current stock price
            risk_per_trade: Risk amount in INR (default ₹500)
            
        Returns:
            Tuple of (quantity, stop_loss_price, stop_loss_distance)
        """
        quantity, sl_dist = self.calculate_quantity(
            total_capital=self.portfolio.total_value,
            risk_per_trade=risk_per_trade,
            atr=atr,
            price=price
        )
        
        stop_loss_price = price - sl_dist  # For long positions
        
        return quantity, stop_loss_price, sl_dist
