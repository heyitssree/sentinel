"""
RSS News Scraper for The Sentinel.
Fetches financial news from Economic Times and Moneycontrol RSS feeds.
Filters headlines by stock ticker keywords.

Features:
- TTL-based caching (default 120 seconds) to reduce API calls
- Configurable via NEWS_CACHE_TTL environment variable
"""
import feedparser
import re
import ssl
import urllib.request
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
import logging
import time
from dataclasses import dataclass, field
from threading import Lock

# Fix SSL certificate issues on macOS
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

logger = logging.getLogger(__name__)

# Cache TTL from environment (default 120 seconds)
NEWS_CACHE_TTL = int(os.getenv("NEWS_CACHE_TTL", "120"))


@dataclass
class NewsItem:
    """Represents a single news headline."""
    ticker: str
    headline: str
    source: str
    timestamp: datetime
    link: str = ""
    summary: str = ""


class NewsScraperError(Exception):
    """Custom exception for news scraper errors."""
    pass


class NewsScraper:
    """
    Scrapes financial news from RSS feeds and filters by stock tickers.
    """
    
    # RSS Feed URLs
    DEFAULT_FEEDS = [
        ("Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
        ("Moneycontrol", "https://www.moneycontrol.com/rss/marketreports.xml"),
        ("Economic Times Stocks", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
        ("Livemint Markets", "https://www.livemint.com/rss/markets"),
        ("Business Standard", "https://www.business-standard.com/rss/markets-106.rss"),
        ("NDTV Profit", "https://feeds.feedburner.com/ndtvprofit-latest"),
        ("Reuters India", "https://www.reuters.com/news/archive/india-RSS"),
        ("Yahoo Finance India", "https://finance.yahoo.com/news/rssindex"),
    ]
    
    # Keyword mappings for stock identification
    TICKER_KEYWORDS = {
        "RELIANCE": ["reliance", "ril", "mukesh ambani", "jio", "reliance industries", "reliance retail"],
        "ICICIBANK": ["icici bank", "icici", "icicibank"],
        "TCS": ["tcs", "tata consultancy", "tata consulting", "tata tech"],
        "INFY": ["infosys", "infy", "narayana murthy", "salil parekh"],
        "HDFCBANK": ["hdfc bank", "hdfcbank", "hdfc"],
        "HINDUNILVR": ["hindustan unilever", "hul", "hindunilvr", "unilever india"],
        "SBIN": ["sbi", "state bank", "sbin", "state bank of india"],
        "BHARTIARTL": ["bharti airtel", "airtel", "bhartiartl", "sunil mittal"],
        "KOTAKBANK": ["kotak", "kotak mahindra", "kotakbank", "uday kotak"],
        "ITC": ["itc", "itc limited", "itc hotels"],
        "JSWSTEEL": ["jsw steel", "jswsteel", "jsw"],
        "TATAMOTORS": ["tata motors", "tatamotors", "tata auto"],
        "WIPRO": ["wipro", "azim premji"],
        "HCLTECH": ["hcl tech", "hcltech", "hcl technologies"],
        "MARUTI": ["maruti", "maruti suzuki", "msil"],
        "AXISBANK": ["axis bank", "axisbank"],
        "SUNPHARMA": ["sun pharma", "sunpharma", "sun pharmaceutical"],
        "TITAN": ["titan", "titan company", "tanishq"],
        "BAJFINANCE": ["bajaj finance", "bajfinance"],
        "ADANIENT": ["adani", "adani enterprises", "adanient", "gautam adani"],
    }
    
    def __init__(self, feeds: List[tuple] = None, watchlist: List[str] = None, cache_ttl: int = None):
        """
        Initialize the news scraper.
        
        Args:
            feeds: List of (source_name, url) tuples
            watchlist: List of stock tickers to filter for
            cache_ttl: Cache TTL in seconds (default from NEWS_CACHE_TTL env var)
        """
        self.feeds = feeds or self.DEFAULT_FEEDS
        self.watchlist = set(watchlist or self.TICKER_KEYWORDS.keys())
        self._seen_headlines: Set[str] = set()
        self._last_fetch_time: Dict[str, datetime] = {}
        self._cache: Dict[str, Dict] = {}
        self._cache_lock = Lock()
        
        # TTL-based caching
        self.cache_ttl = cache_ttl if cache_ttl is not None else NEWS_CACHE_TTL
        self._min_fetch_interval = timedelta(seconds=self.cache_ttl)
        
        # Global news cache (persists across fetch_news calls)
        self._all_news_cache: List[NewsItem] = []
        self._all_news_cache_time: Optional[datetime] = None
        
        logger.info(f"NewsScraper initialized with {len(self.feeds)} feeds, TTL={self.cache_ttl}s")
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison."""
        return re.sub(r'[^\w\s]', '', text.lower())
    
    def _extract_tickers(self, text: str) -> List[str]:
        """
        Extract stock tickers mentioned in text.
        
        Args:
            text: Text to search for ticker mentions
            
        Returns:
            List of matching ticker symbols
        """
        normalized = self._normalize_text(text)
        found_tickers = []
        
        for ticker, keywords in self.TICKER_KEYWORDS.items():
            # Search ALL known tickers, not just watchlist
            for keyword in keywords:
                if keyword in normalized:
                    found_tickers.append(ticker)
                    break
        
        return found_tickers
    
    def _parse_feed(self, source_name: str, url: str) -> List[NewsItem]:
        """
        Parse a single RSS feed.
        
        Args:
            source_name: Name of the news source
            url: RSS feed URL
            
        Returns:
            List of NewsItem objects
        """
        try:
            feed = feedparser.parse(url)
            
            if feed.bozo and feed.bozo_exception:
                logger.warning(f"Feed parsing warning for {source_name}: {feed.bozo_exception}")
            
            items = []
            
            for entry in feed.entries:
                headline = entry.get('title', '').strip()
                
                if not headline:
                    continue
                
                # Skip if we've seen this headline
                headline_hash = self._normalize_text(headline)[:100]
                if headline_hash in self._seen_headlines:
                    continue
                
                # Extract tickers mentioned in headline + summary
                text_to_search = headline + " " + entry.get('summary', '')
                tickers = self._extract_tickers(text_to_search)
                
                if not tickers:
                    continue
                
                # Parse timestamp
                timestamp = datetime.now()
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        timestamp = datetime(*entry.published_parsed[:6])
                    except:
                        pass
                
                # Create news item for each mentioned ticker
                for ticker in tickers:
                    items.append(NewsItem(
                        ticker=ticker,
                        headline=headline,
                        source=source_name,
                        timestamp=timestamp,
                        link=entry.get('link', ''),
                        summary=entry.get('summary', '')[:500]
                    ))
                
                self._seen_headlines.add(headline_hash)
            
            return items
            
        except Exception as e:
            logger.error(f"Error parsing feed {source_name}: {e}")
            return []
    
    def fetch_news(self, force: bool = False) -> List[NewsItem]:
        """
        Fetch news from all configured RSS feeds.
        
        Args:
            force: Force fetch even if within minimum interval
            
        Returns:
            List of NewsItem objects
        """
        # Return cached items if available and not forcing refresh
        if not force and self._all_news_cache_time:
            cache_age = (datetime.now() - self._all_news_cache_time).total_seconds()
            if cache_age < self.cache_ttl and self._all_news_cache:
                logger.debug(f"Returning {len(self._all_news_cache)} cached news items (age: {cache_age:.0f}s)")
                return self._all_news_cache
        
        all_items = []
        
        for source_name, url in self.feeds:
            # Check if we should skip due to rate limiting
            last_fetch = self._last_fetch_time.get(url)
            if not force and last_fetch:
                if datetime.now() - last_fetch < self._min_fetch_interval:
                    logger.debug(f"Skipping {source_name}: too soon since last fetch")
                    continue
            
            logger.info(f"Fetching news from {source_name}")
            items = self._parse_feed(source_name, url)
            all_items.extend(items)
            
            self._last_fetch_time[url] = datetime.now()
            
            # Be nice to servers
            time.sleep(0.5)
        
        # Sort by timestamp (newest first)
        all_items.sort(key=lambda x: x.timestamp, reverse=True)
        
        # Update global cache
        if all_items:
            self._all_news_cache = all_items
            self._all_news_cache_time = datetime.now()
        
        logger.info(f"Fetched {len(all_items)} relevant news items")
        return all_items
    
    def fetch_news_for_ticker(self, ticker: str, force: bool = False) -> List[NewsItem]:
        """
        Fetch news specifically for a single ticker.
        
        Args:
            ticker: Stock ticker symbol
            force: Force fetch even if within minimum interval
            
        Returns:
            List of NewsItem objects for the ticker
        """
        cache_key = f"ticker_{ticker}"
        
        # Check cache with TTL
        with self._cache_lock:
            if not force and cache_key in self._cache:
                cached = self._cache[cache_key]
                age = (datetime.now() - cached['time']).total_seconds()
                if age < self.cache_ttl:
                    logger.debug(f"Cache hit for {ticker} (age: {age:.0f}s)")
                    return cached['items']
        
        # Clear seen headlines on force refresh to get fresh results
        if force:
            self._seen_headlines.clear()
        
        all_news = self.fetch_news(force=force)
        ticker_news = [item for item in all_news if item.ticker == ticker]
        
        # Cache results with TTL
        with self._cache_lock:
            self._cache[cache_key] = {'items': ticker_news, 'time': datetime.now()}
        
        return ticker_news
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics for monitoring."""
        with self._cache_lock:
            now = datetime.now()
            stats = {
                'total_entries': len(self._cache),
                'ttl_seconds': self.cache_ttl,
                'entries': {}
            }
            for key, cached in self._cache.items():
                age = (now - cached['time']).total_seconds()
                stats['entries'][key] = {
                    'age_seconds': age,
                    'items_count': len(cached['items']),
                    'expired': age >= self.cache_ttl
                }
            return stats
    
    def get_recent_headlines(self, ticker: str, limit: int = 10) -> List[str]:
        """
        Get recent headlines for a ticker (for Gemini analysis).
        
        Args:
            ticker: Stock ticker symbol
            limit: Maximum number of headlines
            
        Returns:
            List of headline strings
        """
        items = self.fetch_news_for_ticker(ticker)[:limit]
        return [item.headline for item in items]
    
    def clear_cache(self):
        """Clear the seen headlines cache."""
        self._seen_headlines.clear()
        self._cache.clear()
        self._last_fetch_time.clear()


class MockNewsScraper(NewsScraper):
    """
    Mock news scraper that generates synthetic news for testing.
    Useful when RSS feeds are unavailable or for consistent testing.
    """
    
    SAMPLE_HEADLINES = {
        "RELIANCE": [
            "Reliance Industries Q3 profits beat estimates, Jio subscriber growth continues",
            "RIL plans $10 billion investment in green energy transition",
            "Reliance Retail reports strong festive season sales",
            "Mukesh Ambani announces new AI partnership for Jio platforms",
            "Reliance Industries stock hits all-time high on strong earnings",
        ],
        "ICICIBANK": [
            "ICICI Bank reports 20% YoY growth in net profit",
            "ICICI Bank launches new digital lending platform for SMEs",
            "RBI approves ICICI Bank's acquisition of smaller NBFC",
            "ICICI Bank credit growth outpaces industry average",
            "ICICI Bank expands international operations in Southeast Asia",
        ],
        "TCS": [
            "TCS wins $2 billion deal with major European bank",
            "TCS Q3 revenue grows 8%, beats street expectations",
            "TCS announces plans to hire 40,000 freshers this year",
            "Tata Consultancy Services expands AI and cloud capabilities",
            "TCS CEO confident about demand recovery in financial services",
        ],
        "INFY": [
            "Infosys revises FY24 guidance upward on strong deal wins",
            "Infosys signs multi-year deal with Fortune 500 company",
            "Infosys expands partnership with Microsoft for AI solutions",
            "Infosys Q3 margins expand despite wage hikes",
            "Salil Parekh bullish on digital transformation demand",
        ],
        "HDFCBANK": [
            "HDFC Bank merger synergies ahead of schedule, says CEO",
            "HDFC Bank reports record loan growth in Q3",
            "HDFC Bank maintains asset quality despite industry stress",
            "HDFC Bank launches new credit card targeting millennials",
            "HDFC Bank expands rural banking footprint",
        ],
    }
    
    BEARISH_HEADLINES = {
        "RELIANCE": [
            "Reliance Jio faces increased competition from Airtel 5G",
            "Concerns over Reliance debt levels rise among analysts",
            "Reliance petrochemical margins under pressure from crude prices",
        ],
        "ICICIBANK": [
            "ICICI Bank provisions rise on stressed asset concerns",
            "RBI scrutinizes ICICI Bank's compliance practices",
            "ICICI Bank faces headwinds in corporate lending segment",
        ],
        "TCS": [
            "TCS reports slower deal pipeline in US market",
            "Attrition concerns persist at TCS despite retention efforts",
            "TCS stock faces pressure from IT sector sell-off",
        ],
        "INFY": [
            "Infosys loses key client to competitor Accenture",
            "Infosys faces visa related challenges in US operations",
            "Whistle-blower allegations resurface at Infosys",
        ],
        "HDFCBANK": [
            "HDFC Bank merger integration faces technology challenges",
            "HDFC Bank net interest margins under pressure",
            "Regulatory concerns slow HDFC Bank's expansion plans",
        ],
    }
    
    def __init__(self, watchlist: List[str] = None, sentiment_bias: float = 0.0):
        """
        Initialize mock news scraper.
        
        Args:
            watchlist: List of stock tickers
            sentiment_bias: Bias towards bullish (>0) or bearish (<0) news
        """
        super().__init__(watchlist=watchlist)
        self.sentiment_bias = sentiment_bias
        self._headline_index: Dict[str, int] = {}
    
    def fetch_news(self, force: bool = False) -> List[NewsItem]:
        """Generate mock news items."""
        import random
        
        items = []
        now = datetime.now()
        
        for ticker in self.watchlist:
            # Decide sentiment based on bias + randomness
            is_bullish = random.random() < (0.5 + self.sentiment_bias)
            
            if is_bullish:
                headlines = self.SAMPLE_HEADLINES.get(ticker, [])
            else:
                headlines = self.BEARISH_HEADLINES.get(ticker, [])
            
            if not headlines:
                continue
            
            # Get next headline (rotating through)
            idx = self._headline_index.get(ticker, 0)
            headline = headlines[idx % len(headlines)]
            self._headline_index[ticker] = idx + 1
            
            # Add some time variance
            timestamp = now - timedelta(minutes=random.randint(5, 120))
            
            items.append(NewsItem(
                ticker=ticker,
                headline=headline,
                source="MockNews",
                timestamp=timestamp,
                link="https://example.com/news",
                summary=headline
            ))
        
        items.sort(key=lambda x: x.timestamp, reverse=True)
        return items
