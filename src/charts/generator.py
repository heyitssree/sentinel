"""
Chart generator for The Sentinel.
Generates candlestick charts with indicators for Gemini Vision analysis.

IMPORTANT: Charts use dark theme with high-contrast colors optimized for
LLM vision models. Clean layout with clear labels improves pattern recognition.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import io
import logging

logger = logging.getLogger(__name__)

# Use non-interactive backend for headless operation
plt.switch_backend('Agg')


class ChartGenerator:
    """
    Generate candlestick charts with technical indicators.
    Charts are optimized for Gemini Vision analysis with:
    - Dark theme for better contrast
    - High-contrast colors for EMA lines
    - Clear labels and minimal gridlines
    """
    
    def __init__(self, output_dir: str = "charts"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Dark theme with high-contrast colors for Gemini Vision
        # These colors are optimized for LLM visual pattern recognition
        self.style = {
            'background': '#1a1a2e',      # Deep navy background
            'text': '#ffffff',             # White text
            'grid': '#2d2d44',             # Subtle grid
            'up_candle': '#00f5d4',        # Bright cyan for bullish
            'down_candle': '#ff6b6b',      # Bright red for bearish
            'vwap': '#4361ee',             # Blue dashed for VWAP
            'ema_200': '#9d4edd',          # Purple for 200 EMA (trend)
            'ema_20': '#ff6b35',           # Orange for 20 EMA
            'ema_9': '#00f5d4',            # Cyan for 9 EMA (trailing stop)
            'ema': '#ff6b35',              # Legacy - same as ema_20
            'rsi_line': '#f72585',         # Pink for RSI
            'rsi_overbought': '#ff6b6b',   # Red for overbought zone
            'rsi_oversold': '#00f5d4',     # Cyan for oversold zone
            'entry_line': '#00ff00',       # Green for entry
            'sl_line': '#ff0000',          # Red for stop loss
            'tp_line': '#00ff00',          # Green for take profit
        }
    
    def _setup_dark_style(self, fig, axes):
        """Apply dark theme to figure and axes."""
        fig.patch.set_facecolor(self.style['background'])
        for ax in axes:
            ax.set_facecolor(self.style['background'])
            ax.tick_params(colors=self.style['text'])
            ax.spines['bottom'].set_color(self.style['grid'])
            ax.spines['top'].set_color(self.style['grid'])
            ax.spines['left'].set_color(self.style['grid'])
            ax.spines['right'].set_color(self.style['grid'])
            ax.xaxis.label.set_color(self.style['text'])
            ax.yaxis.label.set_color(self.style['text'])
            ax.title.set_color(self.style['text'])
            ax.grid(True, color=self.style['grid'], linestyle='--', alpha=0.5)
    
    def _draw_candlesticks(self, ax, df: pd.DataFrame):
        """Draw candlestick chart on axis."""
        width = 0.6
        width2 = 0.1
        
        up = df[df['close'] >= df['open']]
        down = df[df['close'] < df['open']]
        
        # Up candles
        ax.bar(up.index, up['close'] - up['open'], width, bottom=up['open'],
               color=self.style['up_candle'], edgecolor=self.style['up_candle'])
        ax.bar(up.index, up['high'] - up['close'], width2, bottom=up['close'],
               color=self.style['up_candle'])
        ax.bar(up.index, up['low'] - up['open'], width2, bottom=up['open'],
               color=self.style['up_candle'])
        
        # Down candles
        ax.bar(down.index, down['close'] - down['open'], width, bottom=down['open'],
               color=self.style['down_candle'], edgecolor=self.style['down_candle'])
        ax.bar(down.index, down['high'] - down['open'], width2, bottom=down['open'],
               color=self.style['down_candle'])
        ax.bar(down.index, down['low'] - down['close'], width2, bottom=down['close'],
               color=self.style['down_candle'])
    
    def generate_chart(self, df: pd.DataFrame, ticker: str,
                       vwap: pd.Series = None, ema: pd.Series = None,
                       rsi: pd.Series = None, timeframe: str = "5min",
                       show_volume: bool = True) -> str:
        """
        Generate a candlestick chart with indicators.
        
        Args:
            df: DataFrame with OHLCV data
            ticker: Stock ticker symbol
            vwap: VWAP series (optional)
            ema: EMA series (optional)
            rsi: RSI series (optional)
            timeframe: Chart timeframe label
            show_volume: Whether to show volume bars
            
        Returns:
            Path to saved chart image
        """
        if df.empty:
            logger.warning(f"Empty dataframe for {ticker}, cannot generate chart")
            return ""
        
        # Reset index for plotting
        df = df.reset_index(drop=True)
        
        # Determine subplot layout
        n_subplots = 1
        height_ratios = [3]
        
        if show_volume:
            n_subplots += 1
            height_ratios.append(1)
        
        if rsi is not None and len(rsi) > 0:
            n_subplots += 1
            height_ratios.append(1)
        
        # Create figure
        fig, axes = plt.subplots(n_subplots, 1, figsize=(12, 8),
                                  gridspec_kw={'height_ratios': height_ratios})
        
        if n_subplots == 1:
            axes = [axes]
        
        self._setup_dark_style(fig, axes)
        
        # Main price chart
        ax_price = axes[0]
        self._draw_candlesticks(ax_price, df)
        
        # Add VWAP
        if vwap is not None and len(vwap) > 0:
            ax_price.plot(vwap.values, color=self.style['vwap'], 
                         linewidth=1.5, label='VWAP', linestyle='--')
        
        # Add EMA
        if ema is not None and len(ema) > 0:
            ax_price.plot(ema.values, color=self.style['ema'],
                         linewidth=1.5, label='EMA20')
        
        ax_price.set_title(f"{ticker} - {timeframe} Chart", fontsize=14, fontweight='bold')
        ax_price.set_ylabel("Price (₹)")
        ax_price.legend(loc='upper left', facecolor=self.style['background'],
                       edgecolor=self.style['grid'], labelcolor=self.style['text'])
        
        current_ax = 1
        
        # Volume chart
        if show_volume and 'volume' in df.columns:
            ax_vol = axes[current_ax]
            colors = [self.style['up_candle'] if df['close'].iloc[i] >= df['open'].iloc[i] 
                     else self.style['down_candle'] for i in range(len(df))]
            ax_vol.bar(df.index, df['volume'], color=colors, alpha=0.7)
            ax_vol.set_ylabel("Volume")
            current_ax += 1
        
        # RSI chart
        if rsi is not None and len(rsi) > 0:
            ax_rsi = axes[current_ax]
            ax_rsi.plot(rsi.values, color=self.style['rsi_line'], linewidth=1.5)
            ax_rsi.axhline(y=70, color=self.style['rsi_overbought'], linestyle='--', alpha=0.7)
            ax_rsi.axhline(y=30, color=self.style['rsi_oversold'], linestyle='--', alpha=0.7)
            ax_rsi.axhline(y=50, color=self.style['grid'], linestyle='-', alpha=0.5)
            ax_rsi.fill_between(range(len(rsi)), 70, 100, alpha=0.1, color=self.style['rsi_overbought'])
            ax_rsi.fill_between(range(len(rsi)), 0, 30, alpha=0.1, color=self.style['rsi_oversold'])
            ax_rsi.set_ylabel("RSI")
            ax_rsi.set_ylim(0, 100)
            
            # Add current RSI value annotation
            current_rsi = rsi.iloc[-1]
            ax_rsi.annotate(f'RSI: {current_rsi:.1f}', 
                           xy=(len(rsi)-1, current_rsi),
                           xytext=(len(rsi)-1 + 2, current_rsi),
                           color=self.style['text'],
                           fontsize=10)
        
        # Set x-axis labels on bottom subplot
        axes[-1].set_xlabel("Candle Index")
        
        plt.tight_layout()
        
        # Save chart
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{ticker}_{timeframe}_{timestamp}.png"
        filepath = self.output_dir / filename
        
        fig.savefig(filepath, dpi=150, facecolor=self.style['background'],
                   edgecolor='none', bbox_inches='tight')
        plt.close(fig)
        
        logger.info(f"Chart saved: {filepath}")
        return str(filepath)
    
    def generate_chart_bytes(self, df: pd.DataFrame, ticker: str,
                             vwap: pd.Series = None, ema: pd.Series = None,
                             rsi: pd.Series = None, timeframe: str = "5min") -> bytes:
        """
        Generate chart and return as bytes (for Gemini API).
        
        Returns:
            PNG image as bytes
        """
        if df.empty:
            return b""
        
        df = df.reset_index(drop=True)
        
        # Create figure
        n_subplots = 2 if rsi is not None else 1
        height_ratios = [3, 1] if rsi is not None else [1]
        
        fig, axes = plt.subplots(n_subplots, 1, figsize=(12, 8),
                                  gridspec_kw={'height_ratios': height_ratios})
        
        if n_subplots == 1:
            axes = [axes]
        
        self._setup_dark_style(fig, axes)
        
        # Main chart
        ax_price = axes[0]
        self._draw_candlesticks(ax_price, df)
        
        if vwap is not None and len(vwap) > 0:
            ax_price.plot(vwap.values, color=self.style['vwap'],
                         linewidth=1.5, label='VWAP', linestyle='--')
        
        if ema is not None and len(ema) > 0:
            ax_price.plot(ema.values, color=self.style['ema'],
                         linewidth=1.5, label='EMA20')
        
        ax_price.set_title(f"{ticker} - {timeframe}", fontsize=14, fontweight='bold')
        ax_price.legend(loc='upper left', facecolor=self.style['background'],
                       edgecolor=self.style['grid'], labelcolor=self.style['text'])
        
        # RSI
        if rsi is not None and len(rsi) > 0:
            ax_rsi = axes[1]
            ax_rsi.plot(rsi.values, color=self.style['rsi_line'], linewidth=1.5)
            ax_rsi.axhline(y=70, color=self.style['rsi_overbought'], linestyle='--', alpha=0.7)
            ax_rsi.axhline(y=30, color=self.style['rsi_oversold'], linestyle='--', alpha=0.7)
            ax_rsi.set_ylabel("RSI")
            ax_rsi.set_ylim(0, 100)
        
        plt.tight_layout()
        
        # Save to bytes buffer
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=150, facecolor=self.style['background'],
                   edgecolor='none', bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        
        return buf.getvalue()
    
    def generate_audit_chart(
        self,
        df: pd.DataFrame,
        ticker: str,
        indicators: Dict[str, pd.Series] = None,
        position: Dict = None,
        timeframe: str = "5min"
    ) -> bytes:
        """
        Generate high-contrast chart optimized for Gemini Vision audit.
        
        Includes all EMAs (200, 20, 9), VWAP, and RSI with clear labels.
        Designed for optimal LLM pattern recognition.
        
        Args:
            df: DataFrame with OHLCV data
            ticker: Stock ticker
            indicators: Dict with 'vwap', 'ema_200', 'ema_20', 'ema_9', 'rsi' series
            position: Optional dict with 'entry', 'sl', 'tp' for position lines
            timeframe: Chart timeframe label
            
        Returns:
            PNG image as bytes
        """
        if df.empty:
            return b""
        
        df = df.reset_index(drop=True)
        indicators = indicators or {}
        
        # Create figure with price and RSI subplots
        fig, axes = plt.subplots(2, 1, figsize=(14, 10),
                                 gridspec_kw={'height_ratios': [4, 1]})
        
        self._setup_dark_style(fig, axes)
        
        ax_price = axes[0]
        ax_rsi = axes[1]
        
        # Draw candlesticks
        self._draw_candlesticks(ax_price, df)
        
        # Add VWAP (blue dashed)
        if 'vwap' in indicators and len(indicators['vwap']) > 0:
            ax_price.plot(
                indicators['vwap'].values,
                color=self.style['vwap'],
                linewidth=2,
                linestyle='--',
                label='VWAP'
            )
        
        # Add 200 EMA (purple - trend filter)
        if 'ema_200' in indicators and len(indicators['ema_200']) > 0:
            ax_price.plot(
                indicators['ema_200'].values,
                color=self.style['ema_200'],
                linewidth=2.5,
                label='200 EMA (TREND)'
            )
        
        # Add 20 EMA (orange)
        if 'ema_20' in indicators and len(indicators['ema_20']) > 0:
            ax_price.plot(
                indicators['ema_20'].values,
                color=self.style['ema_20'],
                linewidth=1.5,
                label='20 EMA'
            )
        
        # Add 9 EMA (cyan - trailing stop)
        if 'ema_9' in indicators and len(indicators['ema_9']) > 0:
            ax_price.plot(
                indicators['ema_9'].values,
                color=self.style['ema_9'],
                linewidth=1.5,
                linestyle=':',
                label='9 EMA (TRAIL)'
            )
        
        # Add position lines if provided
        if position:
            if 'entry' in position:
                ax_price.axhline(
                    y=position['entry'],
                    color=self.style['entry_line'],
                    linewidth=1.5,
                    linestyle='-',
                    alpha=0.8,
                    label=f"Entry: ₹{position['entry']:.2f}"
                )
            if 'sl' in position:
                ax_price.axhline(
                    y=position['sl'],
                    color=self.style['sl_line'],
                    linewidth=1.5,
                    linestyle='--',
                    alpha=0.8,
                    label=f"SL: ₹{position['sl']:.2f}"
                )
            if 'tp' in position:
                ax_price.axhline(
                    y=position['tp'],
                    color=self.style['tp_line'],
                    linewidth=1.5,
                    linestyle='--',
                    alpha=0.8,
                    label=f"TP: ₹{position['tp']:.2f}"
                )
        
        # Title with clear labeling
        ax_price.set_title(
            f"{ticker} - {timeframe} | GEMINI AUDIT CHART",
            fontsize=16,
            fontweight='bold',
            color=self.style['text']
        )
        ax_price.set_ylabel("Price (₹)", fontsize=12)
        
        # Legend with clear background
        ax_price.legend(
            loc='upper left',
            facecolor=self.style['background'],
            edgecolor=self.style['text'],
            labelcolor=self.style['text'],
            fontsize=10
        )
        
        # RSI subplot
        if 'rsi' in indicators and len(indicators['rsi']) > 0:
            rsi = indicators['rsi']
            ax_rsi.plot(rsi.values, color=self.style['rsi_line'], linewidth=2)
            ax_rsi.axhline(y=70, color=self.style['rsi_overbought'], linewidth=1.5, linestyle='--')
            ax_rsi.axhline(y=60, color='#ffd700', linewidth=1, linestyle=':', alpha=0.7)  # 60 line
            ax_rsi.axhline(y=40, color='#ffd700', linewidth=1, linestyle=':', alpha=0.7)  # 40 line
            ax_rsi.axhline(y=30, color=self.style['rsi_oversold'], linewidth=1.5, linestyle='--')
            
            # Fill overbought/oversold zones
            ax_rsi.fill_between(range(len(rsi)), 70, 100, alpha=0.15, color=self.style['rsi_overbought'])
            ax_rsi.fill_between(range(len(rsi)), 0, 30, alpha=0.15, color=self.style['rsi_oversold'])
            
            ax_rsi.set_ylabel("RSI(14)", fontsize=12)
            ax_rsi.set_ylim(0, 100)
            
            # Annotate current RSI
            current_rsi = rsi.iloc[-1]
            ax_rsi.annotate(
                f'RSI: {current_rsi:.1f}',
                xy=(len(rsi) - 1, current_rsi),
                xytext=(len(rsi) - 5, current_rsi + 10),
                color=self.style['text'],
                fontsize=11,
                fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=self.style['text'], lw=1)
            )
        
        ax_rsi.set_xlabel("Candle Index", fontsize=12)
        
        plt.tight_layout()
        
        # Save to bytes
        buf = io.BytesIO()
        fig.savefig(
            buf,
            format='png',
            dpi=150,
            facecolor=self.style['background'],
            edgecolor='none',
            bbox_inches='tight'
        )
        plt.close(fig)
        buf.seek(0)
        
        return buf.getvalue()
    
    def generate_chart_for_auditor(self, df: pd.DataFrame, ticker: str) -> bytes:
        """
        Convenience method to generate audit chart with all indicators calculated.
        
        Args:
            df: DataFrame with OHLCV data (needs 200+ rows for EMA)
            ticker: Stock ticker
            
        Returns:
            PNG image as bytes ready for Gemini Vision
        """
        from src.signals.indicators import TechnicalIndicators
        
        if df.empty or len(df) < 50:
            logger.warning(f"Insufficient data for {ticker} audit chart")
            return b""
        
        ti = TechnicalIndicators()
        
        indicators = {
            'vwap': ti.calculate_vwap(df),
            'ema_200': ti.calculate_ema_200(df),
            'ema_20': ti.calculate_ema(df, 20),
            'ema_9': ti.calculate_ema_9(df),
            'rsi': ti.calculate_rsi(df, 14),
        }
        
        return self.generate_audit_chart(df, ticker, indicators)
    
    def generate_multi_timeframe(self, candles_5min: pd.DataFrame,
                                  candles_15min: pd.DataFrame,
                                  candles_1hr: pd.DataFrame,
                                  ticker: str,
                                  indicators: dict = None) -> Tuple[str, str]:
        """
        Generate 15-min and 1-hour charts for Gemini Vision analysis.
        
        Args:
            candles_5min: 5-minute candle data
            candles_15min: 15-minute candle data (or will be resampled)
            candles_1hr: 1-hour candle data (or will be resampled)
            ticker: Stock ticker
            indicators: Dict with pre-calculated indicators
            
        Returns:
            Tuple of (15min_chart_path, 1hr_chart_path)
        """
        from src.signals.indicators import TechnicalIndicators
        ti = TechnicalIndicators()
        
        charts = []
        
        for df, timeframe in [(candles_15min, "15min"), (candles_1hr, "1hr")]:
            if df.empty:
                charts.append("")
                continue
            
            vwap = ti.calculate_vwap(df)
            ema = ti.calculate_ema(df, 20)
            rsi = ti.calculate_rsi(df, 14)
            
            chart_path = self.generate_chart(
                df, ticker, vwap=vwap, ema=ema, rsi=rsi, timeframe=timeframe
            )
            charts.append(chart_path)
        
        return tuple(charts)
    
    def resample_candles(self, df: pd.DataFrame, 
                         target_interval: str = "15min") -> pd.DataFrame:
        """
        Resample candle data to a larger timeframe.
        
        Args:
            df: DataFrame with OHLCV data and 'timestamp' column
            target_interval: Target interval ('15min', '1h', etc.)
            
        Returns:
            Resampled DataFrame
        """
        if df.empty or 'timestamp' not in df.columns:
            return pd.DataFrame()
        
        df = df.set_index('timestamp')
        
        resampled = df.resample(target_interval).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        
        if 'ticker' in df.columns:
            resampled['ticker'] = df['ticker'].iloc[0]
        
        return resampled.reset_index()
    
    def cleanup_old_charts(self, max_age_hours: int = 24):
        """Remove charts older than specified age."""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        
        for chart_file in self.output_dir.glob("*.png"):
            if datetime.fromtimestamp(chart_file.stat().st_mtime) < cutoff:
                chart_file.unlink()
                logger.debug(f"Removed old chart: {chart_file}")
