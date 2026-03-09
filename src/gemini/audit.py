"""
Trade Auditor - Unified AI audit layer for Sentinel.

Combines:
- Visual chart analysis (Gemini Vision)
- Sentiment analysis from news headlines
- Confluence verification

Returns a confidence score that must exceed 0.8 for trade execution.
"""
import google.generativeai as genai
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass, field
from datetime import datetime
import json
import re
import time
import logging
import base64
import os

logger = logging.getLogger(__name__)


@dataclass
class AuditResult:
    """Result of the trade audit."""
    ticker: str
    confidence_score: float  # 0.0 to 1.0
    bias: str  # BULLISH, BEARISH, NEUTRAL
    reasoning: str
    visual_analysis: Dict = field(default_factory=dict)
    sentiment_analysis: Dict = field(default_factory=dict)
    confluence_verified: bool = False
    passed: bool = False  # True if confidence > 0.8
    timestamp: datetime = field(default_factory=datetime.now)


class TradeAuditor:
    """
    Unified AI auditor that combines visual, sentiment, and technical analysis.
    
    Uses Gemini 2.0 Flash for multimodal analysis:
    1. Chart image analysis for patterns and risk assessment
    2. News headline sentiment analysis
    3. Technical confluence verification (200 EMA, RSI, VWAP)
    """
    
    AUDIT_SYSTEM_PROMPT = """You are a Senior Risk Analyst for a high-frequency trading desk.

Visual Analysis: Look at the provided chart. Identify the trend, key support/resistance, and candle patterns (e.g., engulfing, pin bars).

Sentiment Analysis: Review the provided news headlines. Identify any high-impact regulatory or earnings news.

Confluence Check: Verify the 200 EMA and RSI momentum.

Output Format: Return a JSON object with:
- confidence_score (0.0 to 1.0)
- bias ('BULLISH', 'BEARISH', or 'NEUTRAL')
- reasoning (1 sentence)"""

    AUDIT_USER_PROMPT = """Analyze this trade opportunity for {ticker}:

TECHNICAL DATA:
- Current Price: ₹{price:.2f}
- 200 EMA: ₹{ema_200:.2f} (Price {'above' if price > ema_200 else 'below'} EMA)
- RSI(14): {rsi:.1f}
- VWAP: ₹{vwap:.2f} (Price {'above' if price > vwap else 'below'} VWAP)
- ATR(14): ₹{atr:.2f}

NEWS HEADLINES (last 10):
{headlines}

CHART: [Attached image shows 5-minute candlestick chart with 200 EMA, 20 EMA, and VWAP overlays]

Provide your assessment as JSON only."""

    def __init__(
        self,
        api_key: str = None,
        model: str = "gemini-2.5-flash",
        confidence_threshold: float = 0.8
    ):
        """
        Initialize the TradeAuditor.
        
        Args:
            api_key: Google Gemini API key (defaults to GEMINI_API_KEY env var)
            model: Gemini model to use
            confidence_threshold: Minimum confidence to pass audit (default 0.8)
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model_name = model
        self.confidence_threshold = confidence_threshold
        
        if self.api_key:
            self._setup_client()
        else:
            logger.warning("No Gemini API key provided - using mock auditor")
            self._mock_mode = True
        
        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = 4.0  # 15 RPM = 4 seconds between requests
        
        # Retry settings
        self.max_retries = 3
        self.retry_delay = 2.0
    
    def _setup_client(self):
        """Configure the Gemini client."""
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(
            self.model_name,
            system_instruction=self.AUDIT_SYSTEM_PROMPT
        )
        self._mock_mode = False
        logger.info(f"TradeAuditor initialized with {self.model_name}")
    
    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()
    
    def _parse_response(self, response_text: str) -> Dict:
        """Parse JSON from Gemini response."""
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass
        
        # Try to find JSON in markdown code block
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Try to find JSON object directly
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        
        raise ValueError(f"Could not parse JSON from response: {response_text[:200]}")
    
    def audit(
        self,
        ticker: str,
        chart_image: bytes,
        indicators: Dict[str, float],
        headlines: List[str]
    ) -> AuditResult:
        """
        Perform full trade audit with visual + sentiment + technical analysis.
        
        Args:
            ticker: Stock ticker symbol
            chart_image: PNG chart image as bytes
            indicators: Dict with price, ema_200, rsi, vwap, atr values
            headlines: List of recent news headlines
            
        Returns:
            AuditResult with confidence score and analysis
        """
        if getattr(self, '_mock_mode', True):
            return self._mock_audit(ticker, indicators, headlines)
        
        # Format headlines
        if headlines:
            headlines_text = "\n".join([f"{i+1}. {h}" for i, h in enumerate(headlines[:10])])
        else:
            headlines_text = "No recent news available"
        
        # Build user prompt
        price = indicators.get('price', 0)
        ema_200 = indicators.get('ema_200', 0)
        
        prompt = self.AUDIT_USER_PROMPT.format(
            ticker=ticker,
            price=price,
            ema_200=ema_200,
            rsi=indicators.get('rsi', 50),
            vwap=indicators.get('vwap', price),
            atr=indicators.get('atr', 0),
            headlines=headlines_text
        )
        
        # Prepare image data
        image_data = {
            'mime_type': 'image/png',
            'data': base64.standard_b64encode(chart_image).decode('utf-8')
        }
        
        # Make request with retries
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                
                response = self.model.generate_content([
                    prompt,
                    {'inline_data': image_data}
                ])
                
                result = self._parse_response(response.text)
                
                confidence = max(0.0, min(1.0, float(result.get('confidence_score', 0.5))))
                bias = result.get('bias', 'NEUTRAL').upper()
                reasoning = result.get('reasoning', 'No reasoning provided')
                
                # Verify confluence conditions
                confluence_verified = (
                    price > ema_200 and
                    indicators.get('rsi', 0) > 60 and
                    price > indicators.get('vwap', 0)
                )
                
                passed = confidence >= self.confidence_threshold and bias == 'BULLISH'
                
                audit_result = AuditResult(
                    ticker=ticker,
                    confidence_score=confidence,
                    bias=bias,
                    reasoning=reasoning,
                    visual_analysis={
                        'raw_response': response.text[:500]
                    },
                    sentiment_analysis={
                        'headlines_count': len(headlines),
                        'headlines_analyzed': headlines[:5]
                    },
                    confluence_verified=confluence_verified,
                    passed=passed
                )
                
                logger.info(
                    f"Audit {ticker}: confidence={confidence:.2f}, bias={bias}, "
                    f"passed={passed}"
                )
                return audit_result
                
            except Exception as e:
                logger.warning(f"Audit attempt {attempt+1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error(f"All audit attempts failed for {ticker}")
                    return AuditResult(
                        ticker=ticker,
                        confidence_score=0.0,
                        bias="NEUTRAL",
                        reasoning=f"Audit failed: {str(e)}",
                        passed=False
                    )
    
    def _mock_audit(
        self,
        ticker: str,
        indicators: Dict[str, float],
        headlines: List[str]
    ) -> AuditResult:
        """Mock audit for testing without API."""
        import random
        
        price = indicators.get('price', 0)
        ema_200 = indicators.get('ema_200', 0)
        rsi = indicators.get('rsi', 50)
        vwap = indicators.get('vwap', price)
        
        # Calculate mock confidence based on technicals
        confluence_score = 0
        if price > ema_200:
            confluence_score += 0.3
        if rsi > 60:
            confluence_score += 0.3
        if price > vwap:
            confluence_score += 0.2
        
        # Add some randomness
        confidence = min(1.0, confluence_score + random.uniform(0, 0.3))
        
        if confidence > 0.7:
            bias = "BULLISH"
        elif confidence < 0.4:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"
        
        confluence_verified = price > ema_200 and rsi > 60 and price > vwap
        passed = confidence >= self.confidence_threshold and bias == "BULLISH"
        
        return AuditResult(
            ticker=ticker,
            confidence_score=confidence,
            bias=bias,
            reasoning=f"Mock audit: {bias.lower()} signal with {confidence:.0%} confidence",
            visual_analysis={'mock': True},
            sentiment_analysis={
                'headlines_count': len(headlines),
                'mock': True
            },
            confluence_verified=confluence_verified,
            passed=passed
        )
    
    def quick_sentiment_check(self, ticker: str, headlines: List[str]) -> Tuple[float, str]:
        """
        Quick sentiment-only check (no vision).
        
        Returns:
            Tuple of (sentiment_score, recommendation)
        """
        if not headlines:
            return 0.0, "NEUTRAL"
        
        if getattr(self, '_mock_mode', True):
            import random
            score = random.uniform(-0.5, 0.8)
            rec = "BULLISH" if score > 0.3 else ("BEARISH" if score < -0.3 else "NEUTRAL")
            return score, rec
        
        # Use simpler prompt for quick check
        prompt = f"""Analyze these news headlines for {ticker} and rate sentiment from -1.0 (very bearish) to 1.0 (very bullish).

Headlines:
{chr(10).join(headlines[:5])}

Return JSON: {{"score": <float>, "recommendation": "BULLISH|BEARISH|NEUTRAL"}}"""

        try:
            self._rate_limit()
            response = self.model.generate_content(prompt)
            result = self._parse_response(response.text)
            score = float(result.get('score', 0))
            rec = result.get('recommendation', 'NEUTRAL')
            return score, rec
        except Exception as e:
            logger.warning(f"Quick sentiment check failed: {e}")
            return 0.0, "NEUTRAL"
    
    def should_proceed_with_trade(
        self,
        ticker: str,
        chart_image: bytes,
        indicators: Dict[str, float],
        headlines: List[str]
    ) -> Tuple[bool, AuditResult]:
        """
        Convenience method to check if trade should proceed.
        
        Returns:
            Tuple of (should_proceed, audit_result)
        """
        result = self.audit(ticker, chart_image, indicators, headlines)
        return result.passed, result


class MockTradeAuditor(TradeAuditor):
    """Mock auditor for testing without Gemini API."""
    
    def __init__(self, default_confidence: float = 0.85):
        self.confidence_threshold = 0.8
        self.default_confidence = default_confidence
        self._mock_mode = True
        logger.info("MockTradeAuditor initialized")
    
    def audit(
        self,
        ticker: str,
        chart_image: bytes,
        indicators: Dict[str, float],
        headlines: List[str]
    ) -> AuditResult:
        """Return mock audit result."""
        return self._mock_audit(ticker, indicators, headlines)
