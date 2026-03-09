"""
Technical indicators for The Sentinel trading engine.
Implements VWAP, RSI, and EMA calculations.
"""
import pandas as pd
import numpy as np
from typing import Optional, Tuple, Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    """
    Calculate technical indicators on OHLCV data.
    All methods work with pandas DataFrames containing standard OHLCV columns.
    """
    
    @staticmethod
    def calculate_vwap(df: pd.DataFrame) -> pd.Series:
        """
        Calculate Volume Weighted Average Price (VWAP).
        VWAP resets at the start of each trading day.
        
        Args:
            df: DataFrame with 'high', 'low', 'close', 'volume' columns
            
        Returns:
            Series with VWAP values
        """
        if df.empty:
            return pd.Series(dtype=float)
        
        # Typical price = (High + Low + Close) / 3
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        
        # VWAP = Cumulative(TP * Volume) / Cumulative(Volume)
        cumulative_tp_vol = (typical_price * df['volume']).cumsum()
        cumulative_vol = df['volume'].cumsum()
        
        vwap = cumulative_tp_vol / cumulative_vol
        vwap = vwap.replace([np.inf, -np.inf], np.nan)
        
        return vwap
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Calculate Relative Strength Index (RSI).
        
        Args:
            df: DataFrame with 'close' column
            period: RSI period (default 14)
            
        Returns:
            Series with RSI values (0-100)
        """
        if df.empty or len(df) < period:
            return pd.Series(dtype=float)
        
        # Calculate price changes
        delta = df['close'].diff()
        
        # Separate gains and losses
        gains = delta.where(delta > 0, 0.0)
        losses = (-delta).where(delta < 0, 0.0)
        
        # Calculate average gains and losses using Wilder's smoothing
        avg_gains = gains.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        avg_losses = losses.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        
        # Calculate RS and RSI
        rs = avg_gains / avg_losses
        rsi = 100 - (100 / (1 + rs))
        
        # Handle edge cases
        rsi = rsi.replace([np.inf, -np.inf], np.nan)
        rsi = rsi.fillna(50)  # Neutral RSI when undefined
        
        return rsi
    
    @staticmethod
    def calculate_ema(df: pd.DataFrame, period: int = 20, column: str = 'close') -> pd.Series:
        """
        Calculate Exponential Moving Average (EMA).
        
        Args:
            df: DataFrame with price column
            period: EMA period (default 20)
            column: Column to calculate EMA on (default 'close')
            
        Returns:
            Series with EMA values
        """
        if df.empty:
            return pd.Series(dtype=float)
        
        return df[column].ewm(span=period, adjust=False).mean()
    
    @staticmethod
    def calculate_sma(df: pd.DataFrame, period: int = 20, column: str = 'close') -> pd.Series:
        """
        Calculate Simple Moving Average (SMA).
        
        Args:
            df: DataFrame with price column
            period: SMA period (default 20)
            column: Column to calculate SMA on (default 'close')
            
        Returns:
            Series with SMA values
        """
        if df.empty:
            return pd.Series(dtype=float)
        
        return df[column].rolling(window=period).mean()
    
    @staticmethod
    def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, 
                                   std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate Bollinger Bands.
        
        Args:
            df: DataFrame with 'close' column
            period: Period for SMA (default 20)
            std_dev: Standard deviation multiplier (default 2.0)
            
        Returns:
            Tuple of (upper_band, middle_band, lower_band)
        """
        if df.empty:
            empty = pd.Series(dtype=float)
            return empty, empty, empty
        
        middle = df['close'].rolling(window=period).mean()
        std = df['close'].rolling(window=period).std()
        
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        
        return upper, middle, lower
    
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Calculate Average True Range (ATR).
        
        Args:
            df: DataFrame with 'high', 'low', 'close' columns
            period: ATR period (default 14)
            
        Returns:
            Series with ATR values
        """
        if df.empty or len(df) < 2:
            return pd.Series(dtype=float)
        
        high = df['high']
        low = df['low']
        close = df['close'].shift(1)
        
        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)
        
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        
        return atr
    
    @staticmethod
    def calculate_ema_200(df: pd.DataFrame, column: str = 'close') -> pd.Series:
        """
        Calculate 200-period EMA for trend filtering.
        
        Args:
            df: DataFrame with price column
            column: Column to calculate EMA on (default 'close')
            
        Returns:
            Series with 200 EMA values
        """
        if df.empty:
            return pd.Series(dtype=float)
        return df[column].ewm(span=200, adjust=False).mean()
    
    @staticmethod
    def calculate_ema_9(df: pd.DataFrame, column: str = 'close') -> pd.Series:
        """
        Calculate 9-period EMA for trailing stop.
        
        Args:
            df: DataFrame with price column
            column: Column to calculate EMA on (default 'close')
            
        Returns:
            Series with 9 EMA values
        """
        if df.empty:
            return pd.Series(dtype=float)
        return df[column].ewm(span=9, adjust=False).mean()
    
    @staticmethod
    def calculate_volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """
        Calculate Simple Moving Average of volume for spike detection.
        
        Args:
            df: DataFrame with 'volume' column
            period: SMA period (default 20)
            
        Returns:
            Series with volume SMA values
        """
        if df.empty or 'volume' not in df.columns:
            return pd.Series(dtype=float)
        return df['volume'].rolling(window=period).mean()
    
    @staticmethod
    def calculate_volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """
        Calculate volume ratio (current / SMA) for spike detection.
        
        Args:
            df: DataFrame with 'volume' column
            period: SMA period for baseline (default 20)
            
        Returns:
            Series with volume ratio values (>3 = spike)
        """
        if df.empty or 'volume' not in df.columns:
            return pd.Series(dtype=float)
        volume_sma = df['volume'].rolling(window=period).mean()
        ratio = df['volume'] / volume_sma
        return ratio.replace([np.inf, -np.inf], np.nan).fillna(1.0)
    
    @staticmethod
    def detect_volume_spike(df: pd.DataFrame, threshold: float = 3.0, period: int = 20) -> pd.Series:
        """
        Detect volume spikes where current volume exceeds threshold * average.
        
        Args:
            df: DataFrame with 'volume' column
            threshold: Multiplier for spike detection (default 3.0 = 3x average)
            period: SMA period for baseline (default 20)
            
        Returns:
            Boolean Series (True = volume spike detected)
        """
        if df.empty or 'volume' not in df.columns:
            return pd.Series(dtype=bool)
        
        volume_sma = df['volume'].rolling(window=period).mean()
        spike_threshold = volume_sma * threshold
        is_spike = df['volume'] > spike_threshold
        
        return is_spike.fillna(False)
    
    @staticmethod
    def get_volume_spike_info(df: pd.DataFrame, threshold: float = 3.0, period: int = 20) -> dict:
        """
        Get detailed volume spike information for the latest candle.
        
        Args:
            df: DataFrame with 'volume' column
            threshold: Multiplier for spike detection (default 3.0)
            period: SMA period for baseline (default 20)
            
        Returns:
            Dict with spike status, ratio, and threshold info
        """
        if df.empty or 'volume' not in df.columns or len(df) < period:
            return {
                'is_spike': False,
                'volume': 0,
                'volume_sma': 0,
                'ratio': 1.0,
                'threshold': threshold
            }
        
        volume_sma = df['volume'].rolling(window=period).mean()
        latest_volume = df['volume'].iloc[-1]
        latest_sma = volume_sma.iloc[-1]
        
        if pd.isna(latest_sma) or latest_sma == 0:
            ratio = 1.0
        else:
            ratio = latest_volume / latest_sma
        
        return {
            'is_spike': ratio > threshold,
            'volume': int(latest_volume),
            'volume_sma': float(latest_sma) if not pd.isna(latest_sma) else 0,
            'ratio': float(ratio),
            'threshold': threshold
        }
    
    @staticmethod
    def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, 
                       signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate MACD (Moving Average Convergence Divergence).
        
        Args:
            df: DataFrame with 'close' column
            fast: Fast EMA period (default 12)
            slow: Slow EMA period (default 26)
            signal: Signal line period (default 9)
            
        Returns:
            Tuple of (macd_line, signal_line, histogram)
        """
        if df.empty:
            empty = pd.Series(dtype=float)
            return empty, empty, empty
        
        ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram


class SignalEngine:
    """
    Signal generation engine using technical indicators.
    Implements the trading logic: Price > VWAP + RSI > 60 + Price > EMA(20)
    """
    
    def __init__(self, rsi_period: int = 14, ema_period: int = 20,
                 rsi_entry_threshold: float = 60, rsi_overbought: float = 80):
        self.rsi_period = rsi_period
        self.ema_period = ema_period
        self.rsi_entry_threshold = rsi_entry_threshold
        self.rsi_overbought = rsi_overbought
        self.indicators = TechnicalIndicators()
    
    def analyze(self, df: pd.DataFrame) -> Dict:
        """
        Analyze candle data and generate trading signals.
        
        Args:
            df: DataFrame with OHLCV data, sorted by timestamp ascending
            
        Returns:
            Dict with analysis results and signal
        """
        if df.empty or len(df) < max(self.rsi_period, self.ema_period) + 1:
            return {
                'signal': None,
                'reason': 'Insufficient data',
                'indicators': {}
            }
        
        # Ensure sorted by timestamp
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        # Calculate indicators
        vwap = self.indicators.calculate_vwap(df)
        rsi = self.indicators.calculate_rsi(df, self.rsi_period)
        ema20 = self.indicators.calculate_ema(df, self.ema_period)
        
        # Get latest values
        latest_idx = len(df) - 1
        latest_close = df['close'].iloc[latest_idx]
        latest_vwap = vwap.iloc[latest_idx]
        latest_rsi = rsi.iloc[latest_idx]
        latest_ema = ema20.iloc[latest_idx]
        
        indicators = {
            'close': latest_close,
            'vwap': latest_vwap,
            'rsi': latest_rsi,
            'ema20': latest_ema,
            'price_vs_vwap': latest_close - latest_vwap,
            'price_vs_ema': latest_close - latest_ema,
        }
        
        # Check entry conditions
        price_above_vwap = latest_close > latest_vwap
        rsi_bullish = latest_rsi > self.rsi_entry_threshold
        price_above_ema = latest_close > latest_ema
        rsi_not_overbought = latest_rsi < self.rsi_overbought
        
        conditions = {
            'price_above_vwap': price_above_vwap,
            'rsi_bullish': rsi_bullish,
            'price_above_ema': price_above_ema,
            'rsi_not_overbought': rsi_not_overbought,
        }
        
        # Generate signal
        if price_above_vwap and rsi_bullish and price_above_ema:
            if rsi_not_overbought:
                signal = 'BUY_AUDIT'  # Ready for Gemini audit
                reason = f"Bullish: Price > VWAP (+{latest_close - latest_vwap:.2f}), RSI={latest_rsi:.1f}, Price > EMA20"
            else:
                signal = 'OVERBOUGHT'
                reason = f"Conditions met but RSI overbought ({latest_rsi:.1f} > {self.rsi_overbought})"
        else:
            signal = None
            reasons = []
            if not price_above_vwap:
                reasons.append(f"Price below VWAP ({latest_close:.2f} < {latest_vwap:.2f})")
            if not rsi_bullish:
                reasons.append(f"RSI not bullish ({latest_rsi:.1f} < {self.rsi_entry_threshold})")
            if not price_above_ema:
                reasons.append(f"Price below EMA20 ({latest_close:.2f} < {latest_ema:.2f})")
            reason = "; ".join(reasons) if reasons else "No signal"
        
        return {
            'signal': signal,
            'reason': reason,
            'indicators': indicators,
            'conditions': conditions,
            'timestamp': df['timestamp'].iloc[latest_idx] if 'timestamp' in df.columns else datetime.now()
        }
    
    def should_trigger_audit(self, df: pd.DataFrame) -> Tuple[bool, Dict]:
        """
        Check if conditions warrant a Gemini audit.
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            Tuple of (should_audit, analysis_result)
        """
        analysis = self.analyze(df)
        should_audit = analysis['signal'] == 'BUY_AUDIT'
        return should_audit, analysis
    
    def get_stop_loss(self, entry_price: float, atr: float, 
                      multiplier: float = 1.5) -> float:
        """
        Calculate stop loss based on ATR.
        
        Args:
            entry_price: Entry price
            atr: Current ATR value
            multiplier: ATR multiplier (default 1.5)
            
        Returns:
            Stop loss price
        """
        return entry_price - (atr * multiplier)
    
    def get_take_profit(self, entry_price: float, atr: float,
                        risk_reward: float = 2.0, stop_loss: float = None) -> float:
        """
        Calculate take profit based on risk-reward ratio.
        
        Args:
            entry_price: Entry price
            atr: Current ATR value
            risk_reward: Risk-reward ratio (default 2.0)
            stop_loss: Optional stop loss price
            
        Returns:
            Take profit price
        """
        if stop_loss is None:
            stop_loss = self.get_stop_loss(entry_price, atr)
        
        risk = entry_price - stop_loss
        return entry_price + (risk * risk_reward)
