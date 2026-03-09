"""
Gemini Vision Module (Feature B: Visual Auditor).
Analyzes candlestick charts to validate trading signals.
"""
import google.generativeai as genai
from typing import Optional, Tuple, List
from pathlib import Path
import base64
import json
import re
import time
import logging
from dataclasses import dataclass

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

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        """
        Initialize the visual auditor.
        
        Args:
            api_key: Google Gemini API key
            model: Gemini model to use (must support vision)
        """
        self.api_key = api_key
        self.model_name = model
        self._setup_client()
        
        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = 2.0  # Vision requests need more time
        
        # Retry settings
        self.max_retries = 3
        self.retry_delay = 3.0
    
    def _setup_client(self):
        """Configure the Gemini client."""
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(self.model_name)
        logger.info(f"Gemini visual auditor initialized with {self.model_name}")
    
    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()
    
    def _load_image(self, image_path: str) -> dict:
        """Load image and prepare for Gemini API."""
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Chart image not found: {image_path}")
        
        with open(path, 'rb') as f:
            image_data = f.read()
        
        return {
            'mime_type': 'image/png',
            'data': base64.standard_b64encode(image_data).decode('utf-8')
        }
    
    def _parse_response(self, response_text: str) -> dict:
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
        
        prompt = self.VISION_PROMPT.format(ticker=ticker)
        
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                
                response = self.model.generate_content([
                    prompt,
                    {'inline_data': image_data}
                ])
                
                result = self._parse_response(response.text)
                
                vision_result = VisionResult(
                    ticker=ticker,
                    safety=result.get('safety', 'UNCERTAIN'),
                    confidence=max(0.0, min(1.0, float(result.get('confidence', 0.5)))),
                    pattern_detected=result.get('pattern_detected', 'None'),
                    risk_factors=result.get('risk_factors', []),
                    reasoning=result.get('reasoning', 'No reasoning provided'),
                    rsi_assessment=result.get('rsi_assessment', 'NEUTRAL')
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
                
                content = [prompt] + [{'inline_data': img} for img in images]
                response = self.model.generate_content(content)
                
                result = self._parse_response(response.text)
                
                return VisionResult(
                    ticker=ticker,
                    safety=result.get('safety', 'UNCERTAIN'),
                    confidence=max(0.0, min(1.0, float(result.get('confidence', 0.5)))),
                    pattern_detected=result.get('pattern_detected', 'None'),
                    risk_factors=result.get('risk_factors', []),
                    reasoning=result.get('reasoning', 'No reasoning provided'),
                    rsi_assessment=result.get('rsi_assessment', 'NEUTRAL')
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
        
        image_data = {
            'mime_type': 'image/png',
            'data': base64.standard_b64encode(image_bytes).decode('utf-8')
        }
        
        prompt = self.VISION_PROMPT.format(ticker=ticker)
        
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                
                response = self.model.generate_content([
                    prompt,
                    {'inline_data': image_data}
                ])
                
                result = self._parse_response(response.text)
                
                return VisionResult(
                    ticker=ticker,
                    safety=result.get('safety', 'UNCERTAIN'),
                    confidence=max(0.0, min(1.0, float(result.get('confidence', 0.5)))),
                    pattern_detected=result.get('pattern_detected', 'None'),
                    risk_factors=result.get('risk_factors', []),
                    reasoning=result.get('reasoning', 'No reasoning provided'),
                    rsi_assessment=result.get('rsi_assessment', 'NEUTRAL')
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
    
    def is_safe_to_enter(self, ticker: str, chart_path: str) -> Tuple[bool, VisionResult]:
        """
        Determine if chart analysis supports entering a trade.
        
        Args:
            ticker: Stock ticker
            chart_path: Path to chart image
            
        Returns:
            Tuple of (is_safe, vision_result)
        """
        result = self.analyze_chart(ticker, chart_path)
        is_safe = result.safety == "SAFE" and result.rsi_assessment != "OVERBOUGHT"
        
        if not is_safe:
            logger.info(f"Visual audit blocked trade for {ticker}: "
                       f"safety={result.safety}, rsi={result.rsi_assessment}")
        
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
