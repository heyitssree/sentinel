"""
Gemini Sentiment Analysis Module (Feature A: Vibe-Weighted Entry).
Analyzes news headlines to provide sentiment scoring for trading decisions.
"""
import google.generativeai as genai
from typing import List, Optional, Dict, Tuple
import json
import re
import time
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SentimentResult:
    """Result of sentiment analysis."""
    ticker: str
    score: float  # -1 to 1
    confidence: float  # 0 to 1
    reasoning: str
    key_factors: List[str]
    recommendation: str  # BULLISH, BEARISH, NEUTRAL
    headlines_analyzed: int


class SentimentAnalyzer:
    """
    Analyzes news sentiment using Gemini 2.0 Flash.
    Provides sentiment scores for trading gate decisions.
    """
    
    SENTIMENT_PROMPT = """You are a financial sentiment analyst for Indian stock markets. 
Analyze the following news headlines for {ticker} and provide a sentiment assessment.

HEADLINES:
{headlines}

INSTRUCTIONS:
1. Focus on earnings reports, regulatory news, business expansion, and competitive threats
2. Ignore noise like price movements, analyst ratings, and routine announcements
3. Weight recent news more heavily than older news
4. Consider both direct company news and sector-wide implications

Respond in this exact JSON format:
{{
    "sentiment_score": <float between -1.0 and 1.0>,
    "confidence": <float between 0.0 and 1.0>,
    "reasoning": "<brief 1-2 sentence explanation>",
    "key_factors": ["<factor1>", "<factor2>"],
    "recommendation": "<BULLISH|BEARISH|NEUTRAL>"
}}

SCORING GUIDE:
- 1.0: Extremely positive (major earnings beat, regulatory approval, big contract win)
- 0.5: Moderately positive (good results, expansion news)
- 0.0: Neutral (routine news, mixed signals)
- -0.5: Moderately negative (earnings miss, management issues)
- -1.0: Extremely negative (regulatory action, fraud, major loss)

Return ONLY the JSON, no additional text."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        """
        Initialize the sentiment analyzer.
        
        Args:
            api_key: Google Gemini API key
            model: Gemini model to use
        """
        self.api_key = api_key
        self.model_name = model
        self._setup_client()
        
        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = 1.0  # seconds
        
        # Retry settings
        self.max_retries = 3
        self.retry_delay = 2.0
    
    def _setup_client(self):
        """Configure the Gemini client."""
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(self.model_name)
        logger.info(f"Gemini sentiment analyzer initialized with {self.model_name}")
    
    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()
    
    def _parse_response(self, response_text: str) -> Dict:
        """Parse JSON from Gemini response."""
        # Try to extract JSON from response
        try:
            # Direct parse
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
    
    def analyze(self, ticker: str, headlines: List[str]) -> SentimentResult:
        """
        Analyze sentiment for a stock based on recent headlines.
        
        Args:
            ticker: Stock ticker symbol
            headlines: List of recent news headlines
            
        Returns:
            SentimentResult with score and analysis
        """
        if not headlines:
            logger.warning(f"No headlines provided for {ticker}")
            return SentimentResult(
                ticker=ticker,
                score=0.0,
                confidence=0.0,
                reasoning="No news headlines available for analysis",
                key_factors=[],
                recommendation="NEUTRAL",
                headlines_analyzed=0
            )
        
        # Prepare headlines (numbered for clarity)
        headlines_text = "\n".join([f"{i+1}. {h}" for i, h in enumerate(headlines[:10])])
        
        prompt = self.SENTIMENT_PROMPT.format(
            ticker=ticker,
            headlines=headlines_text
        )
        
        # Make request with retries
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                
                response = self.model.generate_content(prompt)
                result = self._parse_response(response.text)
                
                # Validate and clamp values
                score = max(-1.0, min(1.0, float(result.get('sentiment_score', 0))))
                confidence = max(0.0, min(1.0, float(result.get('confidence', 0.5))))
                
                sentiment_result = SentimentResult(
                    ticker=ticker,
                    score=score,
                    confidence=confidence,
                    reasoning=result.get('reasoning', 'No reasoning provided'),
                    key_factors=result.get('key_factors', []),
                    recommendation=result.get('recommendation', 'NEUTRAL'),
                    headlines_analyzed=len(headlines)
                )
                
                logger.info(f"Sentiment for {ticker}: {score:.2f} ({sentiment_result.recommendation})")
                return sentiment_result
                
            except Exception as e:
                logger.warning(f"Sentiment analysis attempt {attempt+1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error(f"All sentiment analysis attempts failed for {ticker}")
                    return SentimentResult(
                        ticker=ticker,
                        score=0.0,
                        confidence=0.0,
                        reasoning=f"Analysis failed: {str(e)}",
                        key_factors=[],
                        recommendation="NEUTRAL",
                        headlines_analyzed=len(headlines)
                    )
    
    def should_proceed_with_trade(self, ticker: str, headlines: List[str],
                                   threshold: float = 0.0) -> Tuple[bool, SentimentResult]:
        """
        Determine if sentiment supports proceeding with a trade.
        
        Args:
            ticker: Stock ticker
            headlines: Recent news headlines
            threshold: Minimum sentiment score to proceed (default 0.0)
            
        Returns:
            Tuple of (should_proceed, sentiment_result)
        """
        result = self.analyze(ticker, headlines)
        should_proceed = result.score > threshold and result.recommendation != "BEARISH"
        
        if not should_proceed:
            logger.info(f"Trade blocked for {ticker}: sentiment={result.score:.2f}, "
                       f"recommendation={result.recommendation}")
        
        return should_proceed, result


class MockSentimentAnalyzer:
    """
    Mock sentiment analyzer for testing without API calls.
    Returns deterministic results based on ticker.
    """
    
    MOCK_SENTIMENTS = {
        "RELIANCE": 0.6,
        "ICICIBANK": 0.3,
        "TCS": 0.5,
        "INFY": 0.4,
        "HDFCBANK": 0.2,
    }
    
    def __init__(self, default_sentiment: float = 0.3):
        self.default_sentiment = default_sentiment
        logger.info("Mock sentiment analyzer initialized")
    
    def analyze(self, ticker: str, headlines: List[str]) -> SentimentResult:
        """Return mock sentiment result."""
        import random
        
        base_score = self.MOCK_SENTIMENTS.get(ticker, self.default_sentiment)
        # Add some randomness
        score = base_score + random.uniform(-0.2, 0.2)
        score = max(-1.0, min(1.0, score))
        
        if score > 0.3:
            recommendation = "BULLISH"
        elif score < -0.3:
            recommendation = "BEARISH"
        else:
            recommendation = "NEUTRAL"
        
        return SentimentResult(
            ticker=ticker,
            score=score,
            confidence=0.8,
            reasoning=f"Mock analysis: {ticker} shows {recommendation.lower()} sentiment",
            key_factors=["Mock factor 1", "Mock factor 2"],
            recommendation=recommendation,
            headlines_analyzed=len(headlines)
        )
    
    def should_proceed_with_trade(self, ticker: str, headlines: List[str],
                                   threshold: float = 0.0) -> Tuple[bool, SentimentResult]:
        """Mock trade decision."""
        result = self.analyze(ticker, headlines)
        should_proceed = result.score > threshold
        return should_proceed, result
