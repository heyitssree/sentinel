"""
AI-Driven Market Regime Detection Module.

Analyzes Nifty 50 index to identify market regime (TRENDING_UP, TRENDING_DOWN, CHOPPY).
When CHOPPY regime detected:
- Reduce DEFAULT_QUANTITY by 50%
- Tighten Kill Switch threshold by 50%

Timing: Runs at 9:20 AM IST (after first 5-min candle) + every 30 minutes.

Uses google-genai SDK with Pydantic structured outputs.
"""
import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass

from google import genai
from google.genai import types

from .models import RegimeDetectionResponse, MarketRegime

logger = logging.getLogger(__name__)


@dataclass
class RegimeState:
    """Current market regime state."""
    regime: MarketRegime
    confidence: float
    position_size_multiplier: float  # 1.0 = full, 0.5 = half
    kill_switch_multiplier: float    # 1.0 = full limit, 0.5 = half limit
    nifty_trend: str
    volatility_level: str
    reasoning: str
    last_updated: datetime
    

class RegimeDetector:
    """
    Analyzes Nifty 50 index overall every 30 minutes using Gemini.
    
    Detects market regime:
    - TRENDING_UP: Strong bullish trend, full position sizing
    - TRENDING_DOWN: Strong bearish trend, full position sizing (for shorts)
    - CHOPPY: Sideways/range-bound, reduce position size and tighten stops
    
    When CHOPPY detected:
    - Reduce DEFAULT_QUANTITY by 50% to avoid "death by a thousand cuts"
    - Reduce kill switch threshold by 50% (e.g., ₹5000 → ₹2500)
    """
    
    SYSTEM_INSTRUCTION = """You are an expert market analyst for Indian stock markets.
Your role is to analyze Nifty 50 index data and determine the current market regime.

Analysis Framework:
1. Assess trend direction using moving averages (50 EMA, 200 EMA)
2. Evaluate price action - is it making higher highs/lows or range-bound?
3. Check volatility - is the market moving with conviction or chopping around?
4. Consider recent momentum - is there follow-through on moves?

Regime Classification:
- TRENDING_UP: Clear uptrend, price above key MAs, higher highs/lows
- TRENDING_DOWN: Clear downtrend, price below key MAs, lower highs/lows
- CHOPPY: Sideways, whipsawing, no clear direction, tight range

Position Size Recommendation:
- For TRENDING markets: 1.0 (full position size)
- For CHOPPY markets: 0.5 (half position size to avoid overtrading)

Be conservative with CHOPPY detection - only flag it when the market is clearly range-bound
with multiple failed breakouts or reversals within a tight range."""

    def __init__(self, api_key: str = None, model: str = "gemini-2.5-flash"):
        """
        Initialize the regime detector.
        
        Args:
            api_key: Google Gemini API key (or uses GEMINI_API_KEY env var)
            model: Gemini model to use
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model
        self.client = genai.Client(api_key=self.api_key)
        
        self.max_retries = 3
        self.retry_delay = 2.0
        
        # Current regime state
        self._current_regime: Optional[RegimeState] = None
        self._last_check: Optional[datetime] = None
        
        # Check interval (30 minutes)
        self.check_interval_minutes = 30
        
        logger.info(f"RegimeDetector initialized with {model} (new SDK)")
    
    def get_current_regime(self) -> RegimeState:
        """
        Get the current market regime state.
        
        Returns default TRENDING_UP if no regime has been detected yet.
        """
        if self._current_regime is None:
            return RegimeState(
                regime=MarketRegime.TRENDING_UP,
                confidence=0.5,
                position_size_multiplier=1.0,
                kill_switch_multiplier=1.0,
                nifty_trend="Unknown - not yet analyzed",
                volatility_level="NORMAL",
                reasoning="Initial state - regime detection not run yet",
                last_updated=datetime.now()
            )
        return self._current_regime
    
    def should_check_regime(self) -> bool:
        """
        Determine if it's time to check the regime.
        
        Returns True at:
        - 9:20 AM IST (after first 5-min candle)
        - Every 30 minutes thereafter
        """
        now = datetime.now()
        
        # Market hours check (9:15 AM - 3:30 PM)
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        
        if now < market_open or now > market_close:
            return False
        
        # First check at 9:20 AM
        first_check_time = now.replace(hour=9, minute=20, second=0, microsecond=0)
        if self._last_check is None and now >= first_check_time:
            return True
        
        # Subsequent checks every 30 minutes
        if self._last_check is not None:
            elapsed = (now - self._last_check).total_seconds() / 60
            if elapsed >= self.check_interval_minutes:
                return True
        
        return False
    
    def analyze_regime(self, nifty_data: Dict[str, Any]) -> RegimeState:
        """
        Analyze Nifty 50 data and determine market regime.
        
        Args:
            nifty_data: Dict with Nifty 50 OHLCV data and indicators
                Expected keys: current_price, ema_50, ema_200, high_24h, low_24h,
                               volume_ratio, recent_candles (list of OHLC dicts)
        
        Returns:
            RegimeState with current regime and multipliers
        """
        prompt = f"""Analyze the current Nifty 50 market conditions and determine the market regime.

NIFTY 50 DATA:
- Current Price: ₹{nifty_data.get('current_price', 0):.2f}
- 50 EMA: ₹{nifty_data.get('ema_50', 0):.2f}
- 200 EMA: ₹{nifty_data.get('ema_200', 0):.2f}
- 24h High: ₹{nifty_data.get('high_24h', 0):.2f}
- 24h Low: ₹{nifty_data.get('low_24h', 0):.2f}
- 24h Range: {nifty_data.get('range_pct', 0):.2f}%
- Volume vs Average: {nifty_data.get('volume_ratio', 1.0):.1f}x

RECENT PRICE ACTION (last 6 candles):
{self._format_candles(nifty_data.get('recent_candles', []))}

Determine the current market regime and provide your analysis."""

        for attempt in range(self.max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=RegimeDetectionResponse,
                    )
                )
                
                result = RegimeDetectionResponse.model_validate_json(response.text)
                
                # Determine multipliers based on regime
                if result.regime == MarketRegime.CHOPPY:
                    position_mult = 0.5
                    kill_switch_mult = 0.5
                else:
                    position_mult = result.recommended_position_size_multiplier
                    kill_switch_mult = 1.0
                
                regime_state = RegimeState(
                    regime=result.regime,
                    confidence=result.confidence,
                    position_size_multiplier=position_mult,
                    kill_switch_multiplier=kill_switch_mult,
                    nifty_trend=result.nifty_trend,
                    volatility_level=result.volatility_level,
                    reasoning=result.reasoning,
                    last_updated=datetime.now()
                )
                
                self._current_regime = regime_state
                self._last_check = datetime.now()
                
                logger.info(
                    f"Regime detected: {result.regime.value} "
                    f"(confidence: {result.confidence:.0%}, "
                    f"position mult: {position_mult}, "
                    f"kill switch mult: {kill_switch_mult})"
                )
                
                return regime_state
                
            except Exception as e:
                logger.warning(f"Regime detection attempt {attempt+1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
        
        # Return default on failure
        logger.error("All regime detection attempts failed - defaulting to TRENDING_UP")
        return RegimeState(
            regime=MarketRegime.TRENDING_UP,
            confidence=0.3,
            position_size_multiplier=1.0,
            kill_switch_multiplier=1.0,
            nifty_trend="Analysis failed",
            volatility_level="UNKNOWN",
            reasoning="Regime detection failed - using safe default",
            last_updated=datetime.now()
        )
    
    def _format_candles(self, candles: list) -> str:
        """Format candle data for the prompt."""
        if not candles:
            return "No candle data available"
        
        lines = []
        for i, c in enumerate(candles[-6:]):  # Last 6 candles
            change = ((c.get('close', 0) - c.get('open', 0)) / c.get('open', 1)) * 100
            direction = "▲" if change > 0 else "▼" if change < 0 else "─"
            lines.append(
                f"  {direction} O:{c.get('open', 0):.2f} H:{c.get('high', 0):.2f} "
                f"L:{c.get('low', 0):.2f} C:{c.get('close', 0):.2f} ({change:+.2f}%)"
            )
        return "\n".join(lines)


class MockRegimeDetector:
    """Mock regime detector for testing without API calls."""
    
    def __init__(self):
        self._current_regime = None
        logger.info("Mock regime detector initialized")
    
    def get_current_regime(self) -> RegimeState:
        if self._current_regime is None:
            return RegimeState(
                regime=MarketRegime.TRENDING_UP,
                confidence=0.8,
                position_size_multiplier=1.0,
                kill_switch_multiplier=1.0,
                nifty_trend="Mock bullish trend",
                volatility_level="NORMAL",
                reasoning="Mock analysis",
                last_updated=datetime.now()
            )
        return self._current_regime
    
    def should_check_regime(self) -> bool:
        return False
    
    def analyze_regime(self, nifty_data: Dict[str, Any]) -> RegimeState:
        import random
        
        # Randomly select regime for testing
        regimes = [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN, MarketRegime.CHOPPY]
        regime = random.choice(regimes)
        
        if regime == MarketRegime.CHOPPY:
            position_mult = 0.5
            kill_switch_mult = 0.5
        else:
            position_mult = 1.0
            kill_switch_mult = 1.0
        
        self._current_regime = RegimeState(
            regime=regime,
            confidence=0.7,
            position_size_multiplier=position_mult,
            kill_switch_multiplier=kill_switch_mult,
            nifty_trend=f"Mock {regime.value} trend",
            volatility_level="NORMAL",
            reasoning=f"Mock analysis returned {regime.value}",
            last_updated=datetime.now()
        )
        
        return self._current_regime
