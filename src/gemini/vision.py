"""
Gemini Vision Module (Feature B: Visual Auditor).
Analyzes candlestick charts to validate trading signals.

Upgraded to google-genai SDK with:
- New client API
- Pydantic structured outputs
"""
import os
import time
import logging
from typing import Optional, Tuple, List
from pathlib import Path
import base64
from dataclasses import dataclass

from google import genai
from google.genai import types

from .models import VisualAuditResponse, SafetyLevel, RSIAssessment

logger = logging.getLogger(__name__)


@dataclass
class VisionResult:
    """Result of visual chart analysis."""
    ticker: str
    safety: str  # SAFE, RISKY, UNCERTAIN
    confidence: float  # 0 to 1
    pattern_detected: str
    risk_factors: List[str]
    reasoning: str
    rsi_assessment: str  # OVERBOUGHT, OVERSOLD, NEUTRAL


class VisualAuditor:
    """
    Analyzes candlestick charts using Gemini Vision.
    Identifies patterns, overextension, and risk factors.
    """
    
    VISION_PROMPT = """You are a technical analysis expert examining candlestick charts for Indian stocks.
Analyze this chart for {ticker} and assess whether it's SAFE or RISKY to enter a long position.

ANALYSIS CRITERIA:
1. **Overextension**: Is RSI > 80? Is price far above moving averages?
2. **Pattern Recognition**: Look for Cup & Handle, Bull Flag, Breakout, or warning patterns like Rising Wedge, Double Top
3. **Volume**: Is there volume confirmation for the move?
4. **Trend Structure**: Are there higher highs and higher lows?

Respond in this exact JSON format:
{{
    "safety": "<SAFE|RISKY|UNCERTAIN>",
    "confidence": <float between 0.0 and 1.0>,
    "pattern_detected": "<pattern name or 'None'>",
    "risk_factors": ["<risk1>", "<risk2>"],
    "reasoning": "<2-3 sentence explanation>",
    "rsi_assessment": "<OVERBOUGHT|OVERSOLD|NEUTRAL>"
}}

SAFETY GUIDE:
- SAFE: Clean breakout, healthy pullback, RSI 50-70, good volume
- RISKY: Vertical spike, RSI > 80, exhaustion candles, no volume
- UNCERTAIN: Mixed signals, choppy price action

Return ONLY the JSON, no additional text."""

    MULTI_CHART_PROMPT = """You are a technical analyst examining multiple timeframe charts for {ticker}.
I'm showing you a 15-minute chart and a 1-hour chart. Analyze both and determine if entering a long position is SAFE or RISKY.

ANALYSIS CRITERIA:
1. **Multi-Timeframe Alignment**: Do both timeframes show bullish structure?
2. **Overextension Check**: Is RSI > 80 on either timeframe?
3. **Pattern Recognition**: Cup & Handle, Bull Flag, Breakout patterns
4. **Support/Resistance**: Is price near key levels?
5. **Vertical Spikes**: Are there unsustainable vertical moves?

Respond in this exact JSON format:
{{
    "safety": "<SAFE|RISKY|UNCERTAIN>",
    "confidence": <float between 0.0 and 1.0>,
    "pattern_detected": "<pattern name or 'None'>",
    "risk_factors": ["<risk1>", "<risk2>"],
    "reasoning": "<2-3 sentence explanation covering both timeframes>",
    "rsi_assessment": "<OVERBOUGHT|OVERSOLD|NEUTRAL>",
    "timeframe_alignment": "<ALIGNED|DIVERGENT>"
}}

Return ONLY the JSON, no additional text."""

    SYSTEM_INSTRUCTION = """You are a technical analysis expert examining candlestick charts for Indian stocks.
Your role is to assess whether it's SAFE or RISKY to enter a long position.

Analysis Criteria:
1. Overextension: Is RSI > 80? Is price far above moving averages?
2. Pattern Recognition: Cup & Handle, Bull Flag, Breakout, or warning patterns
3. Volume: Is there volume confirmation for the move?
4. Trend Structure: Are there higher highs and higher lows?

Safety Guide:
- SAFE: Clean breakout, healthy pullback, RSI 50-70, good volume
- RISKY: Vertical spike, RSI > 80, exhaustion candles, no volume
- UNCERTAIN: Mixed signals, choppy price action"""

    def __init__(self, api_key: str = None, model: str = "gemini-2.5-flash"):
        """
        Initialize the visual auditor.
        
        Args:
            api_key: Google Gemini API key (or uses GEMINI_API_KEY env var)
            model: Gemini model to use (must support vision)
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model
        self.client = genai.Client(api_key=self.api_key)
        
        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = 2.0  # Vision requests need more time
        
        # Retry settings
        self.max_retries = 3
        self.retry_delay = 3.0
        
        logger.info(f"Gemini visual auditor initialized with {self.model_name} (new SDK)")
    
    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()
    
    def _load_image(self, image_path: str) -> bytes:
        """Load image bytes from file."""
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Chart image not found: {image_path}")
        
        with open(path, 'rb') as f:
            return f.read()
    
    def analyze_chart(self, ticker: str, chart_path: str) -> VisionResult:
        """
        Analyze a single chart image.
        
        Args:
            ticker: Stock ticker symbol
            chart_path: Path to chart PNG image
            
        Returns:
            VisionResult with safety assessment
        """
        try:
            image_data = self._load_image(chart_path)
        except FileNotFoundError as e:
            logger.error(str(e))
            return VisionResult(
                ticker=ticker,
                safety="UNCERTAIN",
                confidence=0.0,
                pattern_detected="None",
                risk_factors=["Chart image not found"],
                reasoning="Could not load chart image for analysis",
                rsi_assessment="NEUTRAL"
            )
        
        prompt = f"Analyze this chart for {ticker} and assess whether it's SAFE or RISKY to enter a long position."
        
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                
                # Use new SDK with Pydantic structured output
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[
                                types.Part.from_text(prompt),
                                types.Part.from_bytes(data=image_data, mime_type="image/png")
                            ]
                        )
                    ],
                    config=types.GenerateContentConfig(
                        system_instruction=self.SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=VisualAuditResponse,
                    )
                )
                
                result = VisualAuditResponse.model_validate_json(response.text)
                
                vision_result = VisionResult(
                    ticker=ticker,
                    safety=result.safety.value,
                    confidence=result.confidence,
                    pattern_detected=result.pattern_detected,
                    risk_factors=result.risk_factors,
                    reasoning=result.reasoning,
                    rsi_assessment=result.rsi_assessment.value
                )
                
                logger.info(f"Visual analysis for {ticker}: {vision_result.safety} "
                           f"(pattern: {vision_result.pattern_detected})")
                return vision_result
                
            except Exception as e:
                logger.warning(f"Vision analysis attempt {attempt+1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error(f"All vision analysis attempts failed for {ticker}")
                    return VisionResult(
                        ticker=ticker,
                        safety="UNCERTAIN",
                        confidence=0.0,
                        pattern_detected="None",
                        risk_factors=[f"Analysis failed: {str(e)}"],
                        reasoning="Vision analysis encountered an error",
                        rsi_assessment="NEUTRAL"
                    )
    
    def analyze_multi_timeframe(self, ticker: str, 
                                 chart_15min: str, 
                                 chart_1hr: str) -> VisionResult:
        """
        Analyze multiple timeframe charts together.
        
        Args:
            ticker: Stock ticker symbol
            chart_15min: Path to 15-minute chart
            chart_1hr: Path to 1-hour chart
            
        Returns:
            VisionResult with combined analysis
        """
        images = []
        for path in [chart_15min, chart_1hr]:
            try:
                images.append(self._load_image(path))
            except FileNotFoundError:
                logger.warning(f"Chart not found: {path}")
        
        if not images:
            return VisionResult(
                ticker=ticker,
                safety="UNCERTAIN",
                confidence=0.0,
                pattern_detected="None",
                risk_factors=["No chart images available"],
                reasoning="Could not load any chart images",
                rsi_assessment="NEUTRAL"
            )
        
        prompt = self.MULTI_CHART_PROMPT.format(ticker=ticker)
        
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                
                # Build parts list for multi-image request using new SDK
                parts = [types.Part.from_text(prompt)]
                for img in images:
                    parts.append(types.Part.from_bytes(data=img, mime_type="image/png"))
                
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[types.Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(
                        system_instruction=self.SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=VisualAuditResponse,
                    )
                )
                
                result = VisualAuditResponse.model_validate_json(response.text)
                
                return VisionResult(
                    ticker=ticker,
                    safety=result.safety.value,
                    confidence=result.confidence,
                    pattern_detected=result.pattern_detected,
                    risk_factors=result.risk_factors,
                    reasoning=result.reasoning,
                    rsi_assessment=result.rsi_assessment.value if hasattr(result, 'rsi_assessment') else "NEUTRAL"
                )
                
            except Exception as e:
                logger.warning(f"Multi-timeframe analysis attempt {attempt+1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
        
        return VisionResult(
            ticker=ticker,
            safety="UNCERTAIN",
            confidence=0.0,
            pattern_detected="None",
            risk_factors=["Multi-timeframe analysis failed"],
            reasoning="Could not complete multi-timeframe analysis",
            rsi_assessment="NEUTRAL"
        )
    
    def analyze_from_bytes(self, ticker: str, image_bytes: bytes) -> VisionResult:
        """
        Analyze chart from bytes (no file needed).
        
        Args:
            ticker: Stock ticker symbol
            image_bytes: PNG image as bytes
            
        Returns:
            VisionResult with safety assessment
        """
        if not image_bytes:
            return VisionResult(
                ticker=ticker,
                safety="UNCERTAIN",
                confidence=0.0,
                pattern_detected="None",
                risk_factors=["Empty image data"],
                reasoning="No chart data provided",
                rsi_assessment="NEUTRAL"
            )
        
        prompt = f"Analyze this chart for {ticker} and assess whether it's SAFE or RISKY to enter a long position."
        
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                
                # Use new SDK with Pydantic structured output
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[
                                types.Part.from_text(prompt),
                                types.Part.from_bytes(data=image_bytes, mime_type="image/png")
                            ]
                        )
                    ],
                    config=types.GenerateContentConfig(
                        system_instruction=self.SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=VisualAuditResponse,
                    )
                )
                
                result = VisualAuditResponse.model_validate_json(response.text)
                
                return VisionResult(
                    ticker=ticker,
                    safety=result.safety.value,
                    confidence=result.confidence,
                    pattern_detected=result.pattern_detected,
                    risk_factors=result.risk_factors,
                    reasoning=result.reasoning,
                    rsi_assessment=result.rsi_assessment.value if hasattr(result, 'rsi_assessment') else "NEUTRAL"
                )
                
            except Exception as e:
                logger.warning(f"Vision analysis attempt {attempt+1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
        
        return VisionResult(
            ticker=ticker,
            safety="UNCERTAIN",
            confidence=0.0,
            pattern_detected="None",
            risk_factors=["Analysis failed after retries"],
            reasoning="Vision analysis encountered errors",
            rsi_assessment="NEUTRAL"
        )
    
    def is_safe_to_enter(self, ticker: str, chart_path: str, 
                          min_confidence: float = 0.6) -> Tuple[bool, VisionResult]:
        """
        Determine if chart analysis supports entering a trade.
        
        Args:
            ticker: Stock ticker
            chart_path: Path to chart image
            min_confidence: Minimum confidence threshold (default 0.6)
            
        Returns:
            Tuple of (is_safe, vision_result)
        """
        result = self.analyze_chart(ticker, chart_path)
        
        # Require SAFE assessment, not overbought RSI, AND sufficient confidence
        is_safe = (
            result.safety == "SAFE" and 
            result.rsi_assessment != "OVERBOUGHT" and
            result.confidence >= min_confidence
        )
        
        if not is_safe:
            reasons = []
            if result.safety != "SAFE":
                reasons.append(f"safety={result.safety}")
            if result.rsi_assessment == "OVERBOUGHT":
                reasons.append(f"rsi={result.rsi_assessment}")
            if result.confidence < min_confidence:
                reasons.append(f"low_confidence={result.confidence:.2f}<{min_confidence}")
            logger.info(f"Visual audit blocked trade for {ticker}: {', '.join(reasons)}")
        
        return is_safe, result


class MockVisualAuditor:
    """
    Mock visual auditor for testing without API calls.
    """
    
    def __init__(self):
        logger.info("Mock visual auditor initialized")
    
    def analyze_chart(self, ticker: str, chart_path: str) -> VisionResult:
        """Return mock vision result."""
        import random
        
        safety_options = ["SAFE", "SAFE", "SAFE", "RISKY", "UNCERTAIN"]
        patterns = ["Bull Flag", "Cup and Handle", "Breakout", "None", "Rising Wedge"]
        
        safety = random.choice(safety_options)
        
        return VisionResult(
            ticker=ticker,
            safety=safety,
            confidence=random.uniform(0.6, 0.9),
            pattern_detected=random.choice(patterns),
            risk_factors=["Mock risk factor"] if safety == "RISKY" else [],
            reasoning=f"Mock analysis: Chart appears {safety.lower()} for entry",
            rsi_assessment="NEUTRAL" if safety == "SAFE" else "OVERBOUGHT"
        )
    
    def analyze_multi_timeframe(self, ticker: str, 
                                 chart_15min: str, 
                                 chart_1hr: str) -> VisionResult:
        """Mock multi-timeframe analysis."""
        return self.analyze_chart(ticker, chart_15min)
    
    def analyze_from_bytes(self, ticker: str, image_bytes: bytes) -> VisionResult:
        """Mock analysis from bytes."""
        return self.analyze_chart(ticker, "mock_path")
    
    def is_safe_to_enter(self, ticker: str, chart_path: str) -> Tuple[bool, VisionResult]:
        """Mock safety check."""
        result = self.analyze_chart(ticker, chart_path)
        is_safe = result.safety == "SAFE"
        return is_safe, result
