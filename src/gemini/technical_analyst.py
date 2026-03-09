"""
Gemini Technical Analysis Module - Direct Data Analysis.
Analyzes raw OHLCV + indicator data instead of chart images.
More efficient and accurate than vision-based analysis.

Upgraded to google-genai SDK with:
- Async client for parallel processing
- Pydantic structured outputs (no manual JSON parsing)
- System instructions for cleaner prompts
"""
import asyncio
import os
import time
import logging
from typing import List, Dict, Tuple
from dataclasses import dataclass

import pandas as pd
from google import genai
from google.genai import types

from .models import TechnicalAnalysisResponse, RecommendationType

logger = logging.getLogger(__name__)


@dataclass
class TechnicalAnalysisResult:
    """Result of technical analysis."""
    ticker: str
    recommendation: str  # BUY, SELL, HOLD
    confidence: float  # 0 to 1
    pattern_detected: str
    support_level: float
    resistance_level: float
    risk_factors: List[str]
    reasoning: str
    

class TechnicalAnalyst:
    """
    Analyzes raw market data using Gemini 2.5 Flash.
    Uses google-genai SDK with Pydantic structured outputs.
    """
    
    SYSTEM_INSTRUCTION = """You are an expert technical analyst for Indian stock markets.
Your role is to analyze OHLCV data and technical indicators to provide trading recommendations.

Analysis Framework:
1. Identify chart patterns (head & shoulders, double top/bottom, flags, wedges, etc.)
2. Assess trend direction and strength using EMAs
3. Identify key support and resistance levels from price action
4. Evaluate momentum using RSI and price vs VWAP
5. Consider risk factors that could invalidate the setup

Recommendation Guide:
- BUY: Strong bullish signals, good risk/reward, momentum supportive
- SELL: Bearish signals, resistance hit, momentum fading
- HOLD: Mixed signals, wait for clearer setup"""

    def __init__(self, api_key: str = None, model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self.client = genai.Client(api_key=self.api_key)
        self.max_retries = 3
        self.retry_delay = 1.0
        self._last_call = 0
        self._min_interval = 0.5  # Rate limiting
        logger.info(f"Technical analyst initialized with {model_name} (new SDK)")
    
    def _rate_limit(self):
        """Ensure minimum interval between API calls."""
        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.time()
    
    async def _rate_limit_async(self):
        """Async rate limiting."""
        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_call = time.time()
    
    def _format_candle_data(self, candles: pd.DataFrame) -> str:
        """Format candle data for the prompt."""
        lines = []
        for _, row in candles.head(10).iterrows():
            lines.append(
                f"  O:{row['open']:.2f} H:{row['high']:.2f} "
                f"L:{row['low']:.2f} C:{row['close']:.2f} V:{int(row['volume'])}"
            )
        return "\n".join(lines)
    
    def analyze(self, ticker: str, candles: pd.DataFrame, 
                indicators: Dict[str, float]) -> TechnicalAnalysisResult:
        """
        Analyze market data and provide recommendation.
        
        Args:
            ticker: Stock ticker symbol
            candles: DataFrame with OHLCV data
            indicators: Dict with rsi, vwap, ema20, ema50, current_price
            
        Returns:
            TechnicalAnalysisResult with recommendation
        """
        if candles.empty or len(candles) < 5:
            return TechnicalAnalysisResult(
                ticker=ticker,
                recommendation="HOLD",
                confidence=0.0,
                pattern_detected="None",
                support_level=0.0,
                resistance_level=0.0,
                risk_factors=["Insufficient data"],
                reasoning="Not enough candle data for analysis"
            )
        
        current_price = indicators.get('current_price', candles.iloc[0]['close'])
        vwap = indicators.get('vwap', current_price)
        price_vs_vwap = ((current_price - vwap) / vwap) * 100 if vwap > 0 else 0
        
        prompt = f"""Analyze the following market data for {ticker} and provide a trading recommendation.

CURRENT INDICATORS:
- Price: ₹{current_price:.2f}
- RSI (14): {indicators.get('rsi', 50):.2f}
- VWAP: ₹{vwap:.2f} (Price vs VWAP: {price_vs_vwap:+.2f}%)
- EMA20: ₹{indicators.get('ema20', current_price):.2f}
- EMA50: ₹{indicators.get('ema50', current_price):.2f}

RECENT OHLCV DATA (last 10 candles, newest first):
{self._format_candle_data(candles)}

Provide your analysis."""
        
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                
                # Use Pydantic structured output - no JSON parsing needed
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=TechnicalAnalysisResponse,
                    )
                )
                
                result = TechnicalAnalysisResponse.model_validate_json(response.text)
                
                analysis_result = TechnicalAnalysisResult(
                    ticker=ticker,
                    recommendation=result.recommendation.value,
                    confidence=result.confidence,
                    pattern_detected=result.pattern_detected,
                    support_level=result.support_level,
                    resistance_level=result.resistance_level,
                    risk_factors=result.risk_factors,
                    reasoning=result.reasoning
                )
                
                logger.info(f"Technical analysis for {ticker}: {result.recommendation.value} "
                           f"(confidence: {result.confidence:.2f}, pattern: {result.pattern_detected})")
                return analysis_result
                
            except Exception as e:
                logger.warning(f"Technical analysis attempt {attempt+1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error(f"All technical analysis attempts failed for {ticker}")
                    return TechnicalAnalysisResult(
                        ticker=ticker,
                        recommendation="HOLD",
                        confidence=0.0,
                        pattern_detected="None",
                        support_level=0.0,
                        resistance_level=0.0,
                        risk_factors=[f"Analysis failed: {str(e)}"],
                        reasoning="Technical analysis encountered an error"
                    )
    
    async def analyze_async(self, ticker: str, candles: pd.DataFrame,
                           indicators: Dict[str, float]) -> TechnicalAnalysisResult:
        """
        Async version of technical analysis for parallel processing.
        """
        if candles.empty or len(candles) < 5:
            return TechnicalAnalysisResult(
                ticker=ticker,
                recommendation="HOLD",
                confidence=0.0,
                pattern_detected="None",
                support_level=0.0,
                resistance_level=0.0,
                risk_factors=["Insufficient data"],
                reasoning="Not enough candle data for analysis"
            )
        
        current_price = indicators.get('current_price', candles.iloc[0]['close'])
        vwap = indicators.get('vwap', current_price)
        price_vs_vwap = ((current_price - vwap) / vwap) * 100 if vwap > 0 else 0
        
        prompt = f"""Analyze the following market data for {ticker} and provide a trading recommendation.

CURRENT INDICATORS:
- Price: ₹{current_price:.2f}
- RSI (14): {indicators.get('rsi', 50):.2f}
- VWAP: ₹{vwap:.2f} (Price vs VWAP: {price_vs_vwap:+.2f}%)
- EMA20: ₹{indicators.get('ema20', current_price):.2f}
- EMA50: ₹{indicators.get('ema50', current_price):.2f}

RECENT OHLCV DATA (last 10 candles, newest first):
{self._format_candle_data(candles)}

Provide your analysis."""
        
        for attempt in range(self.max_retries):
            try:
                await self._rate_limit_async()
                
                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=TechnicalAnalysisResponse,
                    )
                )
                
                result = TechnicalAnalysisResponse.model_validate_json(response.text)
                
                return TechnicalAnalysisResult(
                    ticker=ticker,
                    recommendation=result.recommendation.value,
                    confidence=result.confidence,
                    pattern_detected=result.pattern_detected,
                    support_level=result.support_level,
                    resistance_level=result.resistance_level,
                    risk_factors=result.risk_factors,
                    reasoning=result.reasoning
                )
                
            except Exception as e:
                logger.warning(f"Async technical analysis attempt {attempt+1} failed: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    return TechnicalAnalysisResult(
                        ticker=ticker,
                        recommendation="HOLD",
                        confidence=0.0,
                        pattern_detected="None",
                        support_level=0.0,
                        resistance_level=0.0,
                        risk_factors=[f"Analysis failed: {str(e)}"],
                        reasoning="Technical analysis encountered an error"
                    )
    
    def should_enter_trade(self, ticker: str, candles: pd.DataFrame,
                           indicators: Dict[str, float]) -> Tuple[bool, TechnicalAnalysisResult]:
        """
        Determine if technical analysis supports entering a trade.
        
        Returns:
            Tuple of (should_enter, analysis_result)
        """
        result = self.analyze(ticker, candles, indicators)
        should_enter = (
            result.recommendation == "BUY" and 
            result.confidence >= 0.6 and
            "high risk" not in " ".join(result.risk_factors).lower()
        )
        
        if not should_enter and result.recommendation == "BUY":
            logger.info(f"Trade entry blocked for {ticker}: confidence={result.confidence:.2f}, "
                       f"risks={result.risk_factors}")
        
        return should_enter, result


class MockTechnicalAnalyst:
    """
    Mock technical analyst for testing without API calls.
    Returns deterministic results based on indicators.
    """
    
    def __init__(self):
        logger.info("Mock technical analyst initialized")
    
    def analyze(self, ticker: str, candles: pd.DataFrame,
                indicators: Dict[str, float]) -> TechnicalAnalysisResult:
        """Return mock analysis result based on indicators."""
        import random
        
        rsi = indicators.get('rsi', 50)
        current_price = indicators.get('current_price', 0)
        vwap = indicators.get('vwap', current_price)
        
        # Determine recommendation based on indicators
        if rsi > 70:
            recommendation = "SELL"
            pattern = "Overbought"
            confidence = 0.7 + random.uniform(0, 0.2)
        elif rsi < 30:
            recommendation = "BUY"
            pattern = "Oversold"
            confidence = 0.7 + random.uniform(0, 0.2)
        elif current_price > vwap * 1.01:
            recommendation = "BUY"
            pattern = random.choice(["Bull Flag", "Breakout", "Ascending Triangle"])
            confidence = 0.6 + random.uniform(0, 0.25)
        elif current_price < vwap * 0.99:
            recommendation = "SELL"
            pattern = random.choice(["Bear Flag", "Breakdown", "Descending Triangle"])
            confidence = 0.6 + random.uniform(0, 0.25)
        else:
            recommendation = "HOLD"
            pattern = "Consolidation"
            confidence = 0.5 + random.uniform(0, 0.2)
        
        # Calculate mock support/resistance
        if not candles.empty:
            support = candles['low'].min()
            resistance = candles['high'].max()
        else:
            support = current_price * 0.98
            resistance = current_price * 1.02
        
        risk_factors = []
        if rsi > 65:
            risk_factors.append("RSI approaching overbought")
        if rsi < 35:
            risk_factors.append("RSI approaching oversold")
        if abs(current_price - vwap) / vwap > 0.02:
            risk_factors.append("Price extended from VWAP")
        
        return TechnicalAnalysisResult(
            ticker=ticker,
            recommendation=recommendation,
            confidence=confidence,
            pattern_detected=pattern,
            support_level=support,
            resistance_level=resistance,
            risk_factors=risk_factors if risk_factors else ["Normal market conditions"],
            reasoning=f"Mock analysis: {ticker} shows {pattern} pattern with RSI at {rsi:.1f}"
        )
    
    def should_enter_trade(self, ticker: str, candles: pd.DataFrame,
                           indicators: Dict[str, float]) -> Tuple[bool, TechnicalAnalysisResult]:
        """Mock trade entry decision."""
        result = self.analyze(ticker, candles, indicators)
        should_enter = result.recommendation == "BUY" and result.confidence >= 0.6
        return should_enter, result
