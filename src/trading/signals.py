"""
Confluent Signal Engine for The Sentinel trading platform.
Orchestrates multi-factor entry/exit logic using technical indicators.

This is the "Brain" that combines:
- 200 EMA trend filter
- RSI crossover detection (60 for LONG, 40 for SHORT)
- VWAP execution trigger
- Smart Trailing Stop with time-based exit
"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging

from src.signals.indicators import TechnicalIndicators

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Types of trading signals."""
    LONG_ENTRY = "LONG_ENTRY"
    SHORT_ENTRY = "SHORT_ENTRY"
    EXIT_PROFIT = "EXIT_PROFIT"
    EXIT_STOP = "EXIT_STOP"
    EXIT_TIME = "EXIT_TIME"
    EXIT_EMA = "EXIT_EMA"
    NO_SIGNAL = "NO_SIGNAL"


class StopStage(Enum):
    """Stages of the Smart Trailing Stop."""
    INITIAL = "INITIAL"           # 1.5 ATR from entry
    BREAKEVEN = "BREAKEVEN"       # Moved to entry price at 1% profit
    TRAILING = "TRAILING"         # Trailing 9 EMA at 2% profit


@dataclass
class ConfluenceResult:
    """Result of confluence check."""
    is_valid: bool
    signal_type: SignalType
    confidence: float  # 0.0 to 1.0 based on conditions met
    conditions: Dict[str, bool]
    indicators: Dict[str, float]
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class PositionState:
    """Tracks state of an open position for trailing stop management."""
    ticker: str
    entry_price: float
    entry_time: datetime
    quantity: int
    side: str  # "BUY" or "SELL"
    initial_atr: float
    current_sl: float
    stop_stage: StopStage = StopStage.INITIAL
    highest_price: float = 0.0  # For trailing
    lowest_price: float = float('inf')  # For short trailing


class ConfluentSignalEngine:
    """
    Multi-factor confluence engine for trade entry decisions.
    
    Entry Conditions (ALL must be true for LONG):
    1. Trend: Price > 200 EMA (15-min timeframe)
    2. Momentum: RSI crosses ABOVE 60
    3. Execution: Price > VWAP
    
    For SHORT (inverse):
    1. Price < 200 EMA
    2. RSI crosses BELOW 40
    3. Price < VWAP
    """
    
    def __init__(
        self,
        ema_trend_period: int = 200,
        ema_trail_period: int = 9,
        rsi_period: int = 14,
        rsi_long_threshold: float = 60.0,
        rsi_short_threshold: float = 40.0,
        rsi_overbought: float = 80.0,
        rsi_oversold: float = 20.0,
    ):
        self.ema_trend_period = ema_trend_period
        self.ema_trail_period = ema_trail_period
        self.rsi_period = rsi_period
        self.rsi_long_threshold = rsi_long_threshold
        self.rsi_short_threshold = rsi_short_threshold
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        
        self.indicators = TechnicalIndicators()
        
        # Track previous RSI for crossover detection
        self._prev_rsi: Dict[str, float] = {}
        
        logger.info(
            f"ConfluentSignalEngine initialized: "
            f"EMA={ema_trend_period}, RSI thresholds={rsi_long_threshold}/{rsi_short_threshold}"
        )
    
    def check_confluence(self, df: pd.DataFrame, ticker: str) -> ConfluenceResult:
        """
        Check if all confluence conditions are met for entry.
        
        Args:
            df: DataFrame with OHLCV data (needs 200+ rows for EMA)
            ticker: Stock ticker for RSI crossover tracking
            
        Returns:
            ConfluenceResult with signal and analysis
        """
        # Validate data sufficiency
        min_required = max(self.ema_trend_period, self.rsi_period) + 10
        if df.empty or len(df) < min_required:
            return ConfluenceResult(
                is_valid=False,
                signal_type=SignalType.NO_SIGNAL,
                confidence=0.0,
                conditions={},
                indicators={},
                reason=f"Insufficient data: {len(df)} rows, need {min_required}"
            )
        
        # Ensure sorted by timestamp
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        # Calculate all indicators
        ema_200 = self.indicators.calculate_ema_200(df)
        ema_9 = self.indicators.calculate_ema_9(df)
        ema_20 = self.indicators.calculate_ema(df, 20)
        vwap = self.indicators.calculate_vwap(df)
        rsi = self.indicators.calculate_rsi(df, self.rsi_period)
        atr = self.indicators.calculate_atr(df)
        volume_ratio = self.indicators.calculate_volume_ratio(df)
        
        # Get latest values
        idx = len(df) - 1
        current_price = df['close'].iloc[idx]
        current_ema_200 = ema_200.iloc[idx]
        current_ema_9 = ema_9.iloc[idx]
        current_ema_20 = ema_20.iloc[idx]
        current_vwap = vwap.iloc[idx]
        current_rsi = rsi.iloc[idx]
        current_atr = atr.iloc[idx] if not pd.isna(atr.iloc[idx]) else 0.0
        current_volume_ratio = volume_ratio.iloc[idx] if not pd.isna(volume_ratio.iloc[idx]) else 1.0
        
        # Get previous RSI for crossover detection
        prev_rsi = self._prev_rsi.get(ticker, current_rsi)
        
        # Detect RSI crossover
        rsi_crossed_above_60 = prev_rsi < self.rsi_long_threshold <= current_rsi
        rsi_crossed_below_40 = prev_rsi > self.rsi_short_threshold >= current_rsi
        rsi_above_60 = current_rsi > self.rsi_long_threshold
        rsi_below_40 = current_rsi < self.rsi_short_threshold
        
        # Update previous RSI
        self._prev_rsi[ticker] = current_rsi
        
        # Build indicators dict
        indicators = {
            'price': current_price,
            'ema_200': current_ema_200,
            'ema_20': current_ema_20,
            'ema_9': current_ema_9,
            'vwap': current_vwap,
            'rsi': current_rsi,
            'prev_rsi': prev_rsi,
            'atr': current_atr,
            'volume_ratio': current_volume_ratio,
        }
        
        # Check LONG conditions
        price_above_ema200 = current_price > current_ema_200
        price_above_vwap = current_price > current_vwap
        rsi_not_overbought = current_rsi < self.rsi_overbought
        
        long_conditions = {
            'price_above_ema200': price_above_ema200,
            'rsi_crossed_above_60': rsi_crossed_above_60,
            'rsi_above_60': rsi_above_60,
            'price_above_vwap': price_above_vwap,
            'rsi_not_overbought': rsi_not_overbought,
            'volume_spike': current_volume_ratio > 2.0,
        }
        
        # Check SHORT conditions
        price_below_ema200 = current_price < current_ema_200
        price_below_vwap = current_price < current_vwap
        rsi_not_oversold = current_rsi > self.rsi_oversold
        
        short_conditions = {
            'price_below_ema200': price_below_ema200,
            'rsi_crossed_below_40': rsi_crossed_below_40,
            'rsi_below_40': rsi_below_40,
            'price_below_vwap': price_below_vwap,
            'rsi_not_oversold': rsi_not_oversold,
        }
        
        # Determine signal
        # LONG: Price > 200 EMA + RSI crosses above 60 + Price > VWAP
        long_entry = (
            price_above_ema200 and
            (rsi_crossed_above_60 or rsi_above_60) and
            price_above_vwap and
            rsi_not_overbought
        )
        
        # SHORT: Price < 200 EMA + RSI crosses below 40 + Price < VWAP
        short_entry = (
            price_below_ema200 and
            (rsi_crossed_below_40 or rsi_below_40) and
            price_below_vwap and
            rsi_not_oversold
        )
        
        # Calculate confidence based on conditions met
        if long_entry:
            conditions_met = sum([
                price_above_ema200,
                rsi_crossed_above_60 or rsi_above_60,
                price_above_vwap,
                current_volume_ratio > 1.5,
                current_price > current_ema_20,
            ])
            confidence = conditions_met / 5.0
            
            reason_parts = []
            reason_parts.append(f"Price > 200 EMA (+{current_price - current_ema_200:.2f})")
            reason_parts.append(f"RSI={current_rsi:.1f}" + (" [CROSS]" if rsi_crossed_above_60 else ""))
            reason_parts.append(f"Price > VWAP (+{current_price - current_vwap:.2f})")
            if current_volume_ratio > 2.0:
                reason_parts.append(f"Volume spike {current_volume_ratio:.1f}x")
            
            return ConfluenceResult(
                is_valid=True,
                signal_type=SignalType.LONG_ENTRY,
                confidence=confidence,
                conditions=long_conditions,
                indicators=indicators,
                reason=" | ".join(reason_parts)
            )
        
        elif short_entry:
            conditions_met = sum([
                price_below_ema200,
                rsi_crossed_below_40 or rsi_below_40,
                price_below_vwap,
                current_volume_ratio > 1.5,
            ])
            confidence = conditions_met / 4.0
            
            return ConfluenceResult(
                is_valid=True,
                signal_type=SignalType.SHORT_ENTRY,
                confidence=confidence,
                conditions=short_conditions,
                indicators=indicators,
                reason=f"Bearish: Price < 200 EMA, RSI={current_rsi:.1f}, Price < VWAP"
            )
        
        # No valid signal
        missing = []
        if not price_above_ema200:
            missing.append(f"Price below 200 EMA ({current_price:.2f} < {current_ema_200:.2f})")
        if not (rsi_crossed_above_60 or rsi_above_60):
            missing.append(f"RSI not bullish ({current_rsi:.1f} < {self.rsi_long_threshold})")
        if not price_above_vwap:
            missing.append(f"Price below VWAP ({current_price:.2f} < {current_vwap:.2f})")
        
        return ConfluenceResult(
            is_valid=False,
            signal_type=SignalType.NO_SIGNAL,
            confidence=0.0,
            conditions=long_conditions,
            indicators=indicators,
            reason="; ".join(missing) if missing else "No confluence"
        )
    
    def should_trigger_audit(self, df: pd.DataFrame, ticker: str) -> Tuple[bool, ConfluenceResult]:
        """
        Check if conditions warrant a Gemini audit.
        
        Returns:
            Tuple of (should_audit, confluence_result)
        """
        result = self.check_confluence(df, ticker)
        should_audit = result.is_valid and result.signal_type in [
            SignalType.LONG_ENTRY,
            SignalType.SHORT_ENTRY
        ]
        return should_audit, result


class SmartTrailingStop:
    """
    Manages intelligent trailing stop logic.
    
    Stages:
    1. INITIAL: Stop at entry - 1.5 ATR
    2. BREAKEVEN: At 1% profit, move stop to entry price
    3. TRAILING: At 2% profit, trail using 9-period EMA
    
    Additional:
    - Time-based stop: Tighten to 0.5 ATR if no target hit in 60 minutes
    """
    
    def __init__(
        self,
        initial_atr_multiplier: float = 1.5,
        breakeven_threshold: float = 0.01,  # 1% profit
        trailing_threshold: float = 0.02,   # 2% profit
        time_stop_minutes: int = 60,
        time_stop_atr_multiplier: float = 0.5,
    ):
        self.initial_atr_multiplier = initial_atr_multiplier
        self.breakeven_threshold = breakeven_threshold
        self.trailing_threshold = trailing_threshold
        self.time_stop_minutes = time_stop_minutes
        self.time_stop_atr_multiplier = time_stop_atr_multiplier
        
        # Track positions
        self._positions: Dict[str, PositionState] = {}
        
        logger.info(
            f"SmartTrailingStop initialized: "
            f"ATR mult={initial_atr_multiplier}, "
            f"BE={breakeven_threshold*100}%, Trail={trailing_threshold*100}%"
        )
    
    def register_position(
        self,
        ticker: str,
        entry_price: float,
        entry_time: datetime,
        quantity: int,
        side: str,
        atr: float
    ) -> PositionState:
        """Register a new position for trailing stop management."""
        initial_sl = entry_price - (atr * self.initial_atr_multiplier) if side == "BUY" else \
                     entry_price + (atr * self.initial_atr_multiplier)
        
        position = PositionState(
            ticker=ticker,
            entry_price=entry_price,
            entry_time=entry_time,
            quantity=quantity,
            side=side,
            initial_atr=atr,
            current_sl=initial_sl,
            stop_stage=StopStage.INITIAL,
            highest_price=entry_price,
            lowest_price=entry_price,
        )
        
        self._positions[ticker] = position
        logger.info(f"Registered position {ticker}: entry={entry_price:.2f}, SL={initial_sl:.2f}")
        return position
    
    def update_stop(
        self,
        ticker: str,
        current_price: float,
        ema_9: float,
        current_time: datetime = None
    ) -> Tuple[float, StopStage, Optional[SignalType]]:
        """
        Update trailing stop based on current price and conditions.
        
        Args:
            ticker: Stock ticker
            current_price: Current market price
            ema_9: Current 9-period EMA value
            current_time: Current timestamp (for time-based stop)
            
        Returns:
            Tuple of (new_stop_loss, stop_stage, exit_signal if triggered)
        """
        if ticker not in self._positions:
            logger.warning(f"Position {ticker} not found for stop update")
            return 0.0, StopStage.INITIAL, None
        
        pos = self._positions[ticker]
        current_time = current_time or datetime.now()
        
        # Update highest/lowest price tracking
        if pos.side == "BUY":
            pos.highest_price = max(pos.highest_price, current_price)
        else:
            pos.lowest_price = min(pos.lowest_price, current_price)
        
        # Calculate profit percentage
        if pos.side == "BUY":
            profit_pct = (current_price - pos.entry_price) / pos.entry_price
        else:
            profit_pct = (pos.entry_price - current_price) / pos.entry_price
        
        new_sl = pos.current_sl
        new_stage = pos.stop_stage
        exit_signal = None
        
        # Check time-based stop (60 minutes without hitting target)
        time_elapsed = (current_time - pos.entry_time).total_seconds() / 60
        if time_elapsed >= self.time_stop_minutes and profit_pct < self.trailing_threshold:
            # Tighten stop to 0.5 ATR
            tight_sl = pos.entry_price - (pos.initial_atr * self.time_stop_atr_multiplier) if pos.side == "BUY" else \
                       pos.entry_price + (pos.initial_atr * self.time_stop_atr_multiplier)
            if pos.side == "BUY":
                new_sl = max(pos.current_sl, tight_sl)
            else:
                new_sl = min(pos.current_sl, tight_sl)
            logger.info(f"{ticker}: Time stop triggered at {time_elapsed:.0f}min, tightened SL to {new_sl:.2f}")
        
        # Stage progression based on profit
        if profit_pct >= self.trailing_threshold:
            # Stage 3: Trail with 9 EMA
            new_stage = StopStage.TRAILING
            if pos.side == "BUY":
                # For long: SL is max of current SL and 9 EMA
                new_sl = max(pos.current_sl, ema_9)
            else:
                # For short: SL is min of current SL and 9 EMA
                new_sl = min(pos.current_sl, ema_9)
                
        elif profit_pct >= self.breakeven_threshold:
            # Stage 2: Move to breakeven
            new_stage = StopStage.BREAKEVEN
            if pos.side == "BUY":
                new_sl = max(pos.current_sl, pos.entry_price)
            else:
                new_sl = min(pos.current_sl, pos.entry_price)
        
        # Check if stop loss hit
        if pos.side == "BUY" and current_price <= new_sl:
            exit_signal = SignalType.EXIT_STOP
            logger.info(f"{ticker}: Stop loss hit at {current_price:.2f} (SL={new_sl:.2f})")
        elif pos.side == "SELL" and current_price >= new_sl:
            exit_signal = SignalType.EXIT_STOP
            logger.info(f"{ticker}: Stop loss hit at {current_price:.2f} (SL={new_sl:.2f})")
        
        # Update position state
        if new_sl != pos.current_sl:
            logger.info(f"{ticker}: SL updated {pos.current_sl:.2f} → {new_sl:.2f} ({new_stage.value})")
        pos.current_sl = new_sl
        pos.stop_stage = new_stage
        
        return new_sl, new_stage, exit_signal
    
    def check_ema_exit(self, ticker: str, candle_close: float, ema_9: float) -> Optional[SignalType]:
        """
        Check if a candle closed below 9 EMA (for trailing stage exit).
        
        Args:
            ticker: Stock ticker
            candle_close: Closing price of the candle
            ema_9: 9-period EMA at candle close
            
        Returns:
            EXIT_EMA signal if triggered, None otherwise
        """
        if ticker not in self._positions:
            return None
        
        pos = self._positions[ticker]
        
        # Only check in TRAILING stage
        if pos.stop_stage != StopStage.TRAILING:
            return None
        
        if pos.side == "BUY" and candle_close < ema_9:
            logger.info(f"{ticker}: Candle closed below 9 EMA ({candle_close:.2f} < {ema_9:.2f})")
            return SignalType.EXIT_EMA
        elif pos.side == "SELL" and candle_close > ema_9:
            logger.info(f"{ticker}: Candle closed above 9 EMA ({candle_close:.2f} > {ema_9:.2f})")
            return SignalType.EXIT_EMA
        
        return None
    
    def remove_position(self, ticker: str):
        """Remove a position after exit."""
        if ticker in self._positions:
            del self._positions[ticker]
            logger.info(f"Removed position tracking for {ticker}")
    
    def get_position(self, ticker: str) -> Optional[PositionState]:
        """Get current position state."""
        return self._positions.get(ticker)
    
    def get_all_positions(self) -> Dict[str, PositionState]:
        """Get all tracked positions."""
        return self._positions.copy()


def calculate_atr_position_size(
    total_capital: float,
    risk_per_trade: float,
    atr: float,
    atr_multiplier: float = 1.5,
    price: float = None
) -> int:
    """
    Calculate position size based on ATR risk management.
    
    Args:
        total_capital: Total portfolio value
        risk_per_trade: Max risk in INR (e.g., 500) or as percentage of capital
        atr: Current ATR value
        atr_multiplier: Multiplier for stop loss distance (default 1.5)
        price: Current price (for percentage-based risk)
        
    Returns:
        Number of shares to trade
    """
    if atr <= 0:
        logger.warning("ATR is zero or negative, using default quantity of 1")
        return 1
    
    # If risk_per_trade is < 1, treat as percentage of capital
    if risk_per_trade < 1:
        risk_per_trade = total_capital * risk_per_trade
    
    # Stop loss distance = ATR * multiplier
    stop_loss_dist = atr * atr_multiplier
    
    # Quantity = Risk / Stop Loss Distance
    quantity = int(risk_per_trade / stop_loss_dist)
    
    # Ensure at least 1 share
    quantity = max(1, quantity)
    
    logger.debug(
        f"Position size: risk=₹{risk_per_trade:.0f}, "
        f"ATR={atr:.2f}, SL dist={stop_loss_dist:.2f}, qty={quantity}"
    )
    
    return quantity
