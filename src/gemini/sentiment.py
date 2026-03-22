"""
Gemini Sentiment Analysis Module (Feature A: Vibe-Weighted Entry).
Analyzes news headlines to provide sentiment scoring for trading decisions.

Upgraded to google-genai SDK with:
- Async client for parallel processing
- Pydantic structured outputs (no manual JSON parsing)
- System instructions for cleaner prompts
"""
import asyncio
import os
import time
import logging
from typing import List, Tuple
from dataclasses import dataclass

from google import genai
from google.genai import types

from .models import SentimentResponse, RecommendationType

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
    Analyzes news sentiment using Gemini 2.5 Flash.
    Uses google-genai SDK with Pydantic structured outputs.
    """

    # One-line business description per ticker so Gemini can reason about
    # sector-level or sparse news in company-specific terms.
    TICKER_CONTEXT: dict = {
        "RELIANCE":   "Reliance Industries — India's largest conglomerate; O2C refining/petrochemicals, Jio telecom, Reliance Retail, and green energy.",
        "TCS":        "Tata Consultancy Services — India's largest IT services firm; major clients in global banking, retail, and manufacturing.",
        "HDFCBANK":   "HDFC Bank — India's largest private bank by assets; high CASA ~42%, strong retail and corporate banking franchise.",
        "ICICIBANK":  "ICICI Bank — Large private sector bank; diversified across retail, SME, and corporate loans; digital-first strategy.",
        "INFY":       "Infosys — Tier-1 IT services company; focuses on digital transformation, cloud, and AI for global enterprises.",
        "HINDUNILVR": "Hindustan Unilever — Leading FMCG; dominant in home care, personal care, and foods; high rural India exposure.",
        "SBIN":       "State Bank of India — India's largest public sector bank; significant government borrowings and rural credit exposure.",
        "BHARTIARTL": "Bharti Airtel — India's 2nd-largest telecom; strong 5G rollout, Africa operations, and enterprise data business.",
        "KOTAKBANK":  "Kotak Mahindra Bank — Premium private bank; conservative credit culture, high capital adequacy, wealth management arm.",
        "ITC":        "ITC Limited — Diversified conglomerate; cigarettes (cash cow), FMCG foods, agribusiness, hotels, and paperboards.",
        "LT":         "Larsen & Toubro — India's largest EPC and construction company; strong order book in infra, defence, and hydrocarbons.",
        "AXISBANK":   "Axis Bank — Mid-large private bank; growing retail franchise, improving asset quality post-2020 clean-up.",
        "ASIANPAINT": "Asian Paints — India's largest decorative paints company; pricing power, strong distribution, expanding home décor.",
        "MARUTI":     "Maruti Suzuki — India's largest passenger car maker by volume; dominant in small/mid segment, SUV ramp-up underway.",
        "SUNPHARMA":  "Sun Pharma — India's largest pharma; strong US generics, branded India business, and specialty drugs pipeline.",
        "TITAN":      "Titan Company — Premium consumer brand; jewellery (Tanishq), watches, eyewear, and emerging segments.",
        "ULTRACEMCO": "UltraTech Cement — India's largest cement maker; capacity expansion, strong pricing discipline, pan-India footprint.",
        "BAJFINANCE": "Bajaj Finance — India's leading consumer and SME NBFC; aggressive loan book growth and digital lending platform.",
        "WIPRO":      "Wipro — Tier-1 IT services; focus on consulting, cloud, and cyber-security; margin recovery underway.",
        "HCLTECH":    "HCL Technologies — Tier-1 IT; strong in infrastructure services, engineering R&D, and software products (HCL Software).",
        "ONGC":       "ONGC — State-owned upstream oil & gas; dominates domestic crude and gas production; exposed to oil price cycles.",
        "NTPC":       "NTPC — India's largest power generator; coal-based thermal fleet transitioning to renewables (solar, wind, hydro).",
        "POWERGRID":  "Power Grid Corp — Regulated electricity transmission utility; stable fee income, minimal volume risk.",
        "TATASTEEL":  "Tata Steel — Integrated global steel producer; India operations highly profitable, UK (Port Talbot) in restructuring.",
        "JSWSTEEL":   "JSW Steel — India's largest private steel producer; aggressive capacity expansion, exposed to global steel prices.",
        "ADANIENT":   "Adani Enterprises — Adani Group flagship; incubator for new businesses including green hydrogen, airports, data centres.",
        "ADANIPORTS": "Adani Ports — India's largest private port operator; handles ~27% of India's seaborne cargo, logistics play.",
        "BAJAJ-AUTO": "Bajaj Auto — Top two/three-wheeler maker; strong exports (Africa, ASEAN), premium motorcycles, EV transition.",
        "BAJAJFINSV": "Bajaj Finserv — Holding company for Bajaj Finance (NBFC) and Bajaj Allianz insurance arms.",
        "BPCL":       "BPCL — State PSU oil marketer; fuel retail, refining, and upstream exploration; government disinvestment candidate.",
        "BRITANNIA":  "Britannia Industries — Leading biscuits and dairy brand; margin leverage from wheat/dairy costs, strong distribution.",
        "CIPLA":      "Cipla — Pharma; strong India branded generics, growing US inhalers business, and emerging biosimilars.",
        "COALINDIA":  "Coal India — State-owned coal miner; dominant domestic supplier; high dividend yield, exposed to thermal power demand.",
        "DIVISLAB":   "Divi's Laboratories — API and CRAMS manufacturer; high-margin custom synthesis, key global pharma supply chain partner.",
        "DRREDDY":    "Dr. Reddy's — Pharma; large US generics, branded India/CIS markets, biosimilars, and branded trade generics.",
        "EICHERMOT":  "Eicher Motors — Royal Enfield premium motorcycle brand + VECV (trucks JV with Volvo); high-margin niche.",
        "GRASIM":     "Grasim — Aditya Birla Group; viscose staple fibre, chemicals, and building products; holds 56% of UltraTech.",
        "HDFCLIFE":   "HDFC Life — Private life insurer; strong bancassurance distribution through HDFC Bank, diversified product mix.",
        "HEROMOTOCO": "Hero MotoCorp — India's largest 2-wheeler by volume; mass market commuter segment, rural penetration play.",
        "HINDALCO":   "Hindalco — Aluminium and copper; Novelis (rolled aluminium products globally) is a key value driver.",
        "INDUSINDBK": "IndusInd Bank — Mid-sized private bank; commercial vehicle finance, microfinance, and strong fee income.",
        "M&M":        "Mahindra & Mahindra — SUVs, tractors, and EV (BE series); strong rural and semi-urban demand.",
        "NESTLEIND":  "Nestlé India — FMCG; Maggi noodles, KitKat, Munch, and dairy; premium margins, limited rural reach.",
        "SBILIFE":    "SBI Life Insurance — Largest private life insurer; leverages SBI's vast branch network for distribution.",
        "SHREECEM":   "Shree Cement — High-efficiency cement maker; lowest cost structure in industry, premium to peers justified.",
        "TATACONSUM": "Tata Consumer Products — Beverages (Tata Tea, Tetley), foods (Tata Salt, Soulfull); growth via acquisitions.",
        "TATAMOTORS": "Tata Motors — Passenger vehicles (India + JLR luxury); EV ramp in India, JLR profitability recovery.",
        "TECHM":      "Tech Mahindra — IT services with telecom vertical focus; turnaround under new CEO, margin recovery expected.",
        "APOLLOHOSP": "Apollo Hospitals — India's largest private hospital chain; high-acuity care, Apollo 24|7 digital health, pharmacy.",
        "UPL":        "UPL — Global agrochemicals; post-Arysta acquisition leverage concerns, focus on debt reduction and margin recovery.",
    }

    SYSTEM_INSTRUCTION = """You are a financial sentiment analyst for Indian stock markets.
Your role is to analyze news headlines and assess market sentiment for trading decisions.

Focus on:
- Earnings reports, regulatory news, business expansion, competitive threats
- Weight recent news more heavily than older news
- Consider both direct company news and sector-wide implications

Ignore:
- Price movements, analyst ratings, routine announcements

Scoring Guide:
- 1.0: Extremely positive (major earnings beat, regulatory approval, big contract win)
- 0.5: Moderately positive (good results, expansion news)
- 0.0: Neutral (routine news, mixed signals)
- -0.5: Moderately negative (earnings miss, management issues)
- -1.0: Extremely negative (regulatory action, fraud, major loss)"""

    def __init__(self, api_key: str = None, model: str = "gemini-2.5-flash"):
        """
        Initialize the sentiment analyzer.
        
        Args:
            api_key: Google Gemini API key (or uses GEMINI_API_KEY env var)
            model: Gemini model to use
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model
        self._setup_client()
        
        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = 1.0  # seconds
        
        # Retry settings
        self.max_retries = 3
        self.retry_delay = 2.0
    
    def _setup_client(self):
        """Configure the Gemini client with async support."""
        self.client = genai.Client(api_key=self.api_key)
        logger.info(f"Gemini sentiment analyzer initialized with {self.model_name} (new SDK)")
    
    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()
    
    async def _rate_limit_async(self):
        """Async rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()
    
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
        company_context = self.TICKER_CONTEXT.get(ticker, f"{ticker} — Indian listed stock on NSE.")

        prompt = f"""Analyze the following news headlines for {ticker} and provide a sentiment assessment.

COMPANY: {company_context}

HEADLINES:
{headlines_text}

Consider how each headline specifically affects {ticker}'s business model and financials.
Provide your analysis."""
        
        # Make request with retries using Pydantic structured output
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                
                # Use structured output with Pydantic model - no JSON parsing needed
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=SentimentResponse,
                    )
                )
                
                # Parse structured response directly
                result = SentimentResponse.model_validate_json(response.text)
                
                sentiment_result = SentimentResult(
                    ticker=ticker,
                    score=result.sentiment_score,
                    confidence=result.confidence,
                    reasoning=result.reasoning,
                    key_factors=result.key_factors,
                    recommendation=result.recommendation.value,
                    headlines_analyzed=len(headlines)
                )
                
                logger.info(f"Sentiment for {ticker}: {result.sentiment_score:.2f} ({result.recommendation.value})")
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
    
    async def analyze_async(self, ticker: str, headlines: List[str]) -> SentimentResult:
        """
        Async version of sentiment analysis for parallel processing.
        
        Args:
            ticker: Stock ticker symbol
            headlines: List of recent news headlines
            
        Returns:
            SentimentResult with score and analysis
        """
        if not headlines:
            return SentimentResult(
                ticker=ticker,
                score=0.0,
                confidence=0.0,
                reasoning="No news headlines available for analysis",
                key_factors=[],
                recommendation="NEUTRAL",
                headlines_analyzed=0
            )
        
        headlines_text = "\n".join([f"{i+1}. {h}" for i, h in enumerate(headlines[:10])])
        company_context = self.TICKER_CONTEXT.get(ticker, f"{ticker} — Indian listed stock on NSE.")

        prompt = f"""Analyze the following news headlines for {ticker} and provide a sentiment assessment.

COMPANY: {company_context}

HEADLINES:
{headlines_text}

Consider how each headline specifically affects {ticker}'s business model and financials.
Provide your analysis."""
        
        for attempt in range(self.max_retries):
            try:
                await self._rate_limit_async()
                
                # Async call with structured output
                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=SentimentResponse,
                    )
                )
                
                result = SentimentResponse.model_validate_json(response.text)
                
                return SentimentResult(
                    ticker=ticker,
                    score=result.sentiment_score,
                    confidence=result.confidence,
                    reasoning=result.reasoning,
                    key_factors=result.key_factors,
                    recommendation=result.recommendation.value,
                    headlines_analyzed=len(headlines)
                )
                
            except Exception as e:
                logger.warning(f"Async sentiment analysis attempt {attempt+1} failed: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
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
