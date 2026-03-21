"""
Trade Executors for The Sentinel.
PaperTradeExecutor: local simulation with slippage.
LiveTradeExecutor:  real Zerodha Kite orders, polls for fill confirmation.
"""
from datetime import datetime
from typing import Optional, Dict, List, Tuple
import logging
import time
from dataclasses import dataclass, field

from src.storage.db import SentinelDB, get_db
from src.ingestion.mock_kite import MockKite, MockTicker

logger = logging.getLogger(__name__)


@dataclass
class TradeEntry:
    """Represents a trade entry with all relevant data."""
    ticker: str
    side: str  # BUY or SELL
    quantity: int
    entry_price: float
    entry_time: datetime
    trade_id: int = None
    sentiment_score: float = None
    chart_safety: str = None
    entry_reason: str = None
    stop_loss: float = None
    take_profit: float = None


@dataclass 
class TradeExit:
    """Represents a trade exit."""
    trade_id: int
    exit_price: float
    exit_time: datetime
    exit_reason: str
    pnl: float


class PaperTradeExecutor:
    """
    Executes paper trades with realistic slippage simulation.
    Integrates with DuckDB for trade logging and MockKite for execution.
    """
    
    def __init__(self, kite: MockKite, db: SentinelDB = None,
                 slippage_pct: float = 0.0005, default_quantity: int = 10):
        """
        Initialize the executor.
        
        Args:
            kite: MockKite instance for order execution
            db: SentinelDB instance for logging
            slippage_pct: Slippage percentage (0.0005 = 0.05%)
            default_quantity: Default shares per trade
        """
        self.kite = kite
        self.db = db or get_db()
        self.slippage_pct = slippage_pct
        self.default_quantity = default_quantity
        
        # Track active trades (trade_id -> TradeEntry)
        self._active_trades: Dict[int, TradeEntry] = {}
        
        # Execution stats
        self._stats = {
            'trades_executed': 0,
            'trades_closed': 0,
            'total_pnl': 0.0,
            'winning_trades': 0,
            'losing_trades': 0,
        }
    
    def _apply_slippage(self, price: float, side: str) -> float:
        """Apply slippage to execution price."""
        if side == "BUY":
            return price * (1 + self.slippage_pct)
        else:
            return price * (1 - self.slippage_pct)
    
    def _get_current_price(self, ticker: str) -> float:
        """Get current price from Kite."""
        quote = self.kite.ltp([f"NSE:{ticker}"])
        return quote.get(f"NSE:{ticker}", {}).get('last_price', 0)
    
    def execute_entry(self, ticker: str, side: str = "BUY",
                      quantity: int = None, reason: str = None,
                      sentiment_score: float = None, chart_safety: str = None,
                      stop_loss: float = None, take_profit: float = None) -> Optional[TradeEntry]:
        """
        Execute a trade entry.
        
        Args:
            ticker: Stock ticker
            side: BUY or SELL
            quantity: Number of shares (default: default_quantity)
            reason: Entry reason for logging
            sentiment_score: Gemini sentiment score
            chart_safety: Gemini vision assessment
            stop_loss: Stop loss price
            take_profit: Take profit price
            
        Returns:
            TradeEntry if successful, None otherwise
        """
        quantity = quantity or self.default_quantity
        
        # Get current price
        current_price = self._get_current_price(ticker)
        if current_price <= 0:
            logger.error(f"Invalid price for {ticker}: {current_price}")
            return None
        
        # Apply slippage
        entry_price = self._apply_slippage(current_price, side)
        entry_time = datetime.now()
        
        # Execute order via Kite
        try:
            order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NSE,
                tradingsymbol=ticker,
                transaction_type=side,
                quantity=quantity,
                product=self.kite.PRODUCT_MIS,
                order_type=self.kite.ORDER_TYPE_MARKET
            )
            
            logger.info(f"Order executed: {order_id} | {side} {quantity} {ticker} @ {entry_price:.2f}")
            
        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            return None
        
        # Log to database
        trade_id = self.db.insert_trade(
            ticker=ticker,
            entry_time=entry_time,
            entry_price=entry_price,
            quantity=quantity,
            side=side,
            entry_reason=reason,
            sentiment_score=sentiment_score,
            chart_safety=chart_safety
        )
        
        # Update position in database
        self.db.update_position(
            ticker=ticker,
            quantity=quantity if side == "BUY" else -quantity,
            avg_price=entry_price,
            side=side,
            entry_time=entry_time
        )
        
        # Create trade entry
        trade = TradeEntry(
            ticker=ticker,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            entry_time=entry_time,
            trade_id=trade_id,
            sentiment_score=sentiment_score,
            chart_safety=chart_safety,
            entry_reason=reason,
            stop_loss=stop_loss,
            take_profit=take_profit
        )
        
        self._active_trades[trade_id] = trade
        self._stats['trades_executed'] += 1
        
        return trade
    
    def execute_exit(self, trade_id: int, reason: str = "Manual Exit") -> Optional[TradeExit]:
        """
        Close an existing trade.
        
        Args:
            trade_id: ID of the trade to close
            reason: Exit reason for logging
            
        Returns:
            TradeExit if successful, None otherwise
        """
        trade = self._active_trades.get(trade_id)
        if not trade:
            # Try to get from database
            db_trade = self.db.get_trade(trade_id)
            if not db_trade or db_trade['status'] != 'OPEN':
                logger.warning(f"Trade {trade_id} not found or already closed")
                return None
            
            trade = TradeEntry(
                ticker=db_trade['ticker'],
                side=db_trade['side'],
                quantity=db_trade['quantity'],
                entry_price=db_trade['entry_price'],
                entry_time=db_trade['entry_time'],
                trade_id=trade_id
            )
        
        # Get current price
        current_price = self._get_current_price(trade.ticker)
        if current_price <= 0:
            logger.error(f"Invalid exit price for {trade.ticker}")
            return None
        
        # Determine exit side (opposite of entry)
        exit_side = "SELL" if trade.side == "BUY" else "BUY"
        exit_price = self._apply_slippage(current_price, exit_side)
        exit_time = datetime.now()
        
        # Execute exit order
        try:
            order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NSE,
                tradingsymbol=trade.ticker,
                transaction_type=exit_side,
                quantity=trade.quantity,
                product=self.kite.PRODUCT_MIS,
                order_type=self.kite.ORDER_TYPE_MARKET
            )
            
            logger.info(f"Exit order executed: {order_id}")
            
        except Exception as e:
            logger.error(f"Exit order failed: {e}")
            return None
        
        # Calculate PnL
        pnl = self.db.close_trade(trade_id, exit_time, exit_price, reason)
        
        # Remove position
        self.db.close_position(trade.ticker)
        
        # Update tracking
        if trade_id in self._active_trades:
            del self._active_trades[trade_id]
        
        self._stats['trades_closed'] += 1
        self._stats['total_pnl'] += pnl
        if pnl > 0:
            self._stats['winning_trades'] += 1
        else:
            self._stats['losing_trades'] += 1
        
        trade_exit = TradeExit(
            trade_id=trade_id,
            exit_price=exit_price,
            exit_time=exit_time,
            exit_reason=reason,
            pnl=pnl
        )
        
        logger.info(f"Trade {trade_id} closed | PnL: ₹{pnl:.2f} | Reason: {reason}")
        
        return trade_exit
    
    def exit_by_ticker(self, ticker: str, reason: str = "Ticker Exit") -> List[TradeExit]:
        """Close all trades for a specific ticker."""
        exits = []
        for trade_id, trade in list(self._active_trades.items()):
            if trade.ticker == ticker:
                exit_result = self.execute_exit(trade_id, reason)
                if exit_result:
                    exits.append(exit_result)
        return exits
    
    def close_all_trades(self, reason: str = "Close All") -> List[TradeExit]:
        """Close all active trades."""
        exits = []
        for trade_id in list(self._active_trades.keys()):
            exit_result = self.execute_exit(trade_id, reason)
            if exit_result:
                exits.append(exit_result)
        
        # Also close any Kite positions not in our tracking
        self.kite.close_all_positions()
        
        return exits
    
    def check_stop_loss_take_profit(self) -> List[TradeExit]:
        """
        Check all active trades for stop loss or take profit triggers.
        
        Returns:
            List of TradeExit for any closed trades
        """
        exits = []
        
        for trade_id, trade in list(self._active_trades.items()):
            current_price = self._get_current_price(trade.ticker)
            if current_price <= 0:
                continue
            
            # Check stop loss
            if trade.stop_loss and trade.side == "BUY":
                if current_price <= trade.stop_loss:
                    exit_result = self.execute_exit(trade_id, "Stop Loss Hit")
                    if exit_result:
                        exits.append(exit_result)
                    continue
            
            # Check take profit
            if trade.take_profit and trade.side == "BUY":
                if current_price >= trade.take_profit:
                    exit_result = self.execute_exit(trade_id, "Take Profit Hit")
                    if exit_result:
                        exits.append(exit_result)
                    continue
        
        return exits
    
    def get_active_trades(self) -> List[TradeEntry]:
        """Get all active trades."""
        return list(self._active_trades.values())
    
    def get_position(self, ticker: str) -> Optional[Dict]:
        """Get current position for a ticker."""
        return self.db.get_position(ticker)
    
    def has_position(self, ticker: str) -> bool:
        """Check if there's an open position for a ticker."""
        pos = self.db.get_position(ticker)
        return pos is not None and pos['quantity'] != 0
    
    def get_mtm_pnl(self) -> float:
        """Get current mark-to-market PnL across all positions."""
        total_mtm = 0.0
        
        for trade in self._active_trades.values():
            current_price = self._get_current_price(trade.ticker)
            if current_price > 0:
                if trade.side == "BUY":
                    unrealized = (current_price - trade.entry_price) * trade.quantity
                else:
                    unrealized = (trade.entry_price - current_price) * trade.quantity
                total_mtm += unrealized
        
        return total_mtm
    
    def get_stats(self) -> Dict:
        """Get execution statistics."""
        win_rate = 0.0
        if self._stats['trades_closed'] > 0:
            win_rate = self._stats['winning_trades'] / self._stats['trades_closed'] * 100
        
        return {
            **self._stats,
            'active_trades': len(self._active_trades),
            'unrealized_pnl': self.get_mtm_pnl(),
            'win_rate': win_rate,
        }
    
    def reset_day(self):
        """Reset for a new trading day."""
        self._active_trades.clear()
        self._stats = {
            'trades_executed': 0,
            'trades_closed': 0,
            'total_pnl': 0.0,
            'winning_trades': 0,
            'losing_trades': 0,
        }
        self.kite.reset_day()


class LiveTradeExecutor:
    """
    Executes real Zerodha Kite market orders.
    Same public interface as PaperTradeExecutor so the engine can swap them at runtime.
    """

    # How long to wait for order fill confirmation (seconds)
    FILL_POLL_INTERVAL = 0.5
    FILL_POLL_TIMEOUT = 15

    def __init__(self, kite, db: SentinelDB = None, slippage_pct: float = 0.0):
        """
        Args:
            kite: RealKite instance (already authenticated)
            db: SentinelDB for logging
            slippage_pct: Not applied to live orders (Zerodha handles real fills),
                          kept for interface compatibility.
        """
        self.kite = kite
        self.db = db or get_db()
        self.slippage_pct = slippage_pct  # unused for live; kept for compat

        self._active_trades: Dict[int, TradeEntry] = {}
        self._stats = {
            'trades_executed': 0,
            'trades_closed': 0,
            'total_pnl': 0.0,
            'winning_trades': 0,
            'losing_trades': 0,
        }

    def _get_current_price(self, ticker: str) -> float:
        quote = self.kite.ltp([f"NSE:{ticker}"])
        return quote.get(f"NSE:{ticker}", {}).get('last_price', 0)

    def _place_and_confirm(self, ticker: str, transaction_type: str, quantity: int) -> Optional[float]:
        """
        Place a Zerodha market order and poll until filled.
        Returns the average fill price, or None on failure.
        """
        try:
            order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NSE,
                tradingsymbol=ticker,
                transaction_type=transaction_type,
                quantity=quantity,
                product=self.kite.PRODUCT_MIS,
                order_type=self.kite.ORDER_TYPE_MARKET,
            )
            logger.info(f"[LIVE] Order placed: {order_id} | {transaction_type} {quantity} {ticker}")
        except Exception as e:
            logger.error(f"[LIVE] Order placement failed for {ticker}: {e}")
            return None

        # Poll for fill confirmation
        deadline = time.time() + self.FILL_POLL_TIMEOUT
        while time.time() < deadline:
            time.sleep(self.FILL_POLL_INTERVAL)
            try:
                history = self.kite.order_history(order_id)
                if history:
                    last = history[-1]
                    status = last.get('status', '').upper()
                    if status == 'COMPLETE':
                        fill_price = float(last.get('average_price', 0))
                        logger.info(f"[LIVE] Order {order_id} filled @ ₹{fill_price:.2f}")
                        return fill_price
                    elif status in ('REJECTED', 'CANCELLED'):
                        logger.error(f"[LIVE] Order {order_id} {status}: {last.get('status_message')}")
                        return None
            except Exception as e:
                logger.warning(f"[LIVE] Poll error for {order_id}: {e}")

        logger.error(f"[LIVE] Order {order_id} fill timeout after {self.FILL_POLL_TIMEOUT}s")
        return None

    def execute_entry(self, ticker: str, side: str = "BUY",
                      quantity: int = None, reason: str = None,
                      sentiment_score: float = None, chart_safety: str = None,
                      stop_loss: float = None, take_profit: float = None) -> Optional[TradeEntry]:
        quantity = quantity or 1
        fill_price = self._place_and_confirm(ticker, side, quantity)
        if fill_price is None or fill_price <= 0:
            return None

        entry_time = datetime.now()
        trade_id = self.db.insert_trade(
            ticker=ticker,
            entry_time=entry_time,
            entry_price=fill_price,
            quantity=quantity,
            side=side,
            entry_reason=reason,
            sentiment_score=sentiment_score,
            chart_safety=chart_safety,
        )
        self.db.update_position(
            ticker=ticker,
            quantity=quantity if side == "BUY" else -quantity,
            avg_price=fill_price,
            side=side,
            entry_time=entry_time,
        )

        trade = TradeEntry(
            ticker=ticker, side=side, quantity=quantity,
            entry_price=fill_price, entry_time=entry_time,
            trade_id=trade_id, sentiment_score=sentiment_score,
            chart_safety=chart_safety, entry_reason=reason,
            stop_loss=stop_loss, take_profit=take_profit,
        )
        self._active_trades[trade_id] = trade
        self._stats['trades_executed'] += 1
        return trade

    def execute_exit(self, trade_id: int, reason: str = "Exit") -> Optional[TradeExit]:
        trade = self._active_trades.get(trade_id)
        if not trade:
            db_trade = self.db.get_trade(trade_id)
            if not db_trade or db_trade['status'] != 'OPEN':
                return None
            trade = TradeEntry(
                ticker=db_trade['ticker'], side=db_trade['side'],
                quantity=db_trade['quantity'], entry_price=db_trade['entry_price'],
                entry_time=db_trade['entry_time'], trade_id=trade_id,
            )

        exit_side = "SELL" if trade.side == "BUY" else "BUY"
        fill_price = self._place_and_confirm(trade.ticker, exit_side, trade.quantity)
        if fill_price is None or fill_price <= 0:
            return None

        exit_time = datetime.now()
        pnl = self.db.close_trade(trade_id, exit_time, fill_price, reason)
        self.db.close_position(trade.ticker)

        if trade_id in self._active_trades:
            del self._active_trades[trade_id]

        self._stats['trades_closed'] += 1
        self._stats['total_pnl'] += pnl
        if pnl > 0:
            self._stats['winning_trades'] += 1
        else:
            self._stats['losing_trades'] += 1

        logger.info(f"[LIVE] Trade {trade_id} closed | PnL: ₹{pnl:.2f} | {reason}")
        return TradeExit(trade_id=trade_id, exit_price=fill_price,
                         exit_time=exit_time, exit_reason=reason, pnl=pnl)

    def exit_by_ticker(self, ticker: str, reason: str = "Ticker Exit") -> List[TradeExit]:
        exits = []
        for trade_id, trade in list(self._active_trades.items()):
            if trade.ticker == ticker:
                result = self.execute_exit(trade_id, reason)
                if result:
                    exits.append(result)
        return exits

    def close_all_trades(self, reason: str = "Close All") -> List[TradeExit]:
        return [r for tid in list(self._active_trades) for r in [self.execute_exit(tid, reason)] if r]

    def get_active_trades(self) -> List[TradeEntry]:
        return list(self._active_trades.values())

    def has_position(self, ticker: str) -> bool:
        pos = self.db.get_position(ticker)
        return pos is not None and pos['quantity'] != 0

    def get_mtm_pnl(self) -> float:
        total = 0.0
        for trade in self._active_trades.values():
            price = self._get_current_price(trade.ticker)
            if price > 0:
                total += (price - trade.entry_price) * trade.quantity if trade.side == "BUY" \
                    else (trade.entry_price - price) * trade.quantity
        return total

    def get_stats(self) -> Dict:
        closed = self._stats['trades_closed']
        return {
            **self._stats,
            'active_trades': len(self._active_trades),
            'unrealized_pnl': self.get_mtm_pnl(),
            'win_rate': (self._stats['winning_trades'] / closed * 100) if closed > 0 else 0.0,
        }

    def reset_day(self):
        self._active_trades.clear()
        self._stats = {k: 0 if isinstance(v, int) else 0.0 for k, v in self._stats.items()}
