"""
Gemini Technical Analysis Module - Direct Data Analysis.
Analyzes raw OHLCV + indicator data instead of chart images.
More efficient and accurate than vision-based analysis.
"""
import google.generativeai as genai
from typing import List, Optional, Dict, Tuple
import pandas as pd
import json
import re
import time
import logging
from dataclasses import dataclass

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
    Analyzes raw market data using Gemini 2.0 Flash.
    Provides pattern detection and trade recommendations from numerical data.
    """
    
    ANALYSIS_PROMPT = """You are an expert technical analyst for Indian stock markets.
Analyze the following market data for {ticker} and provide a trading recommendation.

CURRENT INDICATORS:
- Price: ₹{current_price:.2f}
- RSI (14): {rsi:.2f}
- VWAP: ₹{vwap:.2f} (Price vs VWAP: {price_vs_vwap:+.2f}%)
- EMA20: ₹{ema20:.2f}
- EMA50: ₹{ema50:.2f}

RECENT OHLCV DATA (last 10 candles, newest first):
{candle_data}

INSTRUCTIONS:
1. Identify any chart patterns (head & shoulders, double top/bottom, flags, wedges, etc.)
2. Assess trend direction and strength
3. Identify key support and resistance levels
4. Evaluate momentum and potential reversals
5. Consider risk factors

Respond in this exact JSON format:
{{
    "recommendation": "<BUY|SELL|HOLD>",
    "confidence": <float between 0.0 and 1.0>,
    "pattern_detected": "<pattern name or 'None'>",
    "support_level": <float>,
    "resistance_level": <float>,
    "risk_factors": ["<factor1>", "<factor2>"],
    "reasoning": "<brief 2-3 sentence explanation>"
}}

RECOMMENDATION GUIDE:
- BUY: Strong bullish signals, good risk/reward, momentum supportive
- SELL: Bearish signals, resistance hit, momentum fading
- HOLD: Mixed signals, wait for clearer setup
"""

    def __init__(self, api_key: str = None, model_name: str = "gemini-2.5-flash"):
        if api_key:
            genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        self.max_retries = 3
        self.retry_delay = 1.0
        self._last_call = 0
        self._min_interval = 0.5  # Rate limiting
        logger.info(f"Technical analyst initialized with {model_name}")
    
    def _rate_limit(self):
        """Ensure minimum interval between API calls."""
        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
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
    
    def _parse_response(self, response_text: str) -> dict:
        """Parse JSON from model response."""
        # Try direct JSON parse
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass
        
        # Try to extract JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Try to find JSON object in text
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        
        raise ValueError(f"Could not parse JSON from response: {response_text[:200]}")
    
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
        
        prompt = self.ANALYSIS_PROMPT.format(
            ticker=ticker,
            current_price=current_price,
            rsi=indicators.get('rsi', 50),
            vwap=vwap,
            price_vs_vwap=price_vs_vwap,
            ema20=indicators.get('ema20', current_price),
            ema50=indicators.get('ema50', current_price),
            candle_data=self._format_candle_data(candles)
        )
        
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                
                response = self.model.generate_content(prompt)
                result = self._parse_response(response.text)
                
                analysis_result = TechnicalAnalysisResult(
                    ticker=ticker,
                    recommendation=result.get('recommendation', 'HOLD'),
                    confidence=max(0.0, min(1.0, float(result.get('confidence', 0.5)))),
                    pattern_detected=result.get('pattern_detected', 'None'),
                    support_level=float(result.get('support_level', 0)),
                    resistance_level=float(result.get('resistance_level', 0)),
                    risk_factors=result.get('risk_factors', []),
                    reasoning=result.get('reasoning', 'No reasoning provided')
                )
                
                logger.info(f"Technical analysis for {ticker}: {analysis_result.recommendation} "
                           f"(confidence: {analysis_result.confidence:.2f}, pattern: {analysis_result.pattern_detected})")
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
