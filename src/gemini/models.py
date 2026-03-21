"""
Pydantic response models for Gemini AI outputs.
Used with google-genai SDK for structured outputs - eliminates manual JSON parsing.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class RecommendationType(str, Enum):
    """Trading recommendation types."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class MarketRegime(str, Enum):
    """Market regime types for regime detection."""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    CHOPPY = "CHOPPY"


class ExitTimingVerdict(str, Enum):
    """Exit timing assessment."""
    GOOD = "GOOD"
    TOO_EARLY = "TOO_EARLY"
    TOO_LATE = "TOO_LATE"
    MIXED = "MIXED"


class SafetyLevel(str, Enum):
    """Chart safety assessment levels."""
    SAFE = "SAFE"
    RISKY = "RISKY"
    UNCERTAIN = "UNCERTAIN"


class RSIAssessment(str, Enum):
    """RSI assessment levels."""
    OVERBOUGHT = "OVERBOUGHT"
    OVERSOLD = "OVERSOLD"
    NEUTRAL = "NEUTRAL"


# ============================================================================
# Sentiment Analysis Models
# ============================================================================

class SentimentResponse(BaseModel):
    """Structured response for sentiment analysis."""
    sentiment_score: float = Field(
        ..., 
        ge=-1.0, 
        le=1.0, 
        description="Sentiment score from -1.0 (extremely negative) to 1.0 (extremely positive)"
    )
    confidence: float = Field(
        ..., 
        ge=0.0, 
        le=1.0, 
        description="Confidence in the analysis from 0.0 to 1.0"
    )
    reasoning: str = Field(
        ..., 
        description="Brief 1-2 sentence explanation of the sentiment"
    )
    key_factors: List[str] = Field(
        default_factory=list, 
        description="Key factors driving the sentiment"
    )
    recommendation: RecommendationType = Field(
        default=RecommendationType.NEUTRAL,
        description="Overall recommendation: BULLISH, BEARISH, or NEUTRAL"
    )


# ============================================================================
# Technical Analysis Models
# ============================================================================

class TechnicalAnalysisResponse(BaseModel):
    """Structured response for technical analysis."""
    recommendation: RecommendationType = Field(
        ..., 
        description="Trading recommendation: BUY, SELL, or HOLD"
    )
    confidence: float = Field(
        ..., 
        ge=0.0, 
        le=1.0, 
        description="Confidence in the recommendation"
    )
    pattern_detected: str = Field(
        default="None", 
        description="Chart pattern detected (e.g., Bull Flag, Head & Shoulders)"
    )
    support_level: float = Field(
        default=0.0, 
        description="Key support price level"
    )
    resistance_level: float = Field(
        default=0.0, 
        description="Key resistance price level"
    )
    risk_factors: List[str] = Field(
        default_factory=list, 
        description="Risk factors to consider"
    )
    reasoning: str = Field(
        ..., 
        description="Brief 2-3 sentence explanation"
    )


# ============================================================================
# Visual Audit Models
# ============================================================================

class ChartSafety(str, Enum):
    """Chart safety assessment."""
    SAFE = "SAFE"
    RISKY = "RISKY"
    NEUTRAL = "NEUTRAL"


class VisualAuditResponse(BaseModel):
    """Structured response for visual chart audit."""
    safety: ChartSafety = Field(
        ..., 
        description="Overall chart safety: SAFE or RISKY"
    )
    pattern_detected: str = Field(
        default="None", 
        description="Visual pattern detected"
    )
    overextension_risk: bool = Field(
        default=False, 
        description="Whether price appears overextended"
    )
    confidence: float = Field(
        ..., 
        ge=0.0, 
        le=1.0, 
        description="Confidence in the assessment"
    )
    reasoning: str = Field(
        ..., 
        description="Brief explanation of the visual assessment"
    )


# ============================================================================
# Autopsy Models
# ============================================================================

class AutopsyResponse(BaseModel):
    """Structured response for post-trade autopsy."""
    key_observations: List[str] = Field(
        default_factory=list, 
        description="Key observations from trade analysis"
    )
    stop_loss_suggestion: str = Field(
        ..., 
        description="Specific stop-loss improvement suggestion"
    )
    overall_assessment: str = Field(
        ..., 
        description="1-2 sentence summary of day's performance"
    )
    improvement_areas: List[str] = Field(
        default_factory=list, 
        description="Areas for improvement"
    )
    best_trade_analysis: str = Field(
        default="", 
        description="Why the best trade worked"
    )
    worst_trade_analysis: str = Field(
        default="", 
        description="Why the worst trade failed"
    )
    exit_timing_verdict: ExitTimingVerdict = Field(
        default=ExitTimingVerdict.MIXED, 
        description="Assessment of exit timing"
    )
    opportunity_cost_note: Optional[str] = Field(
        default=None,
        description="Analysis of what happened 2h after exits"
    )


# ============================================================================
# Regime Detection Models
# ============================================================================

class RegimeDetectionResponse(BaseModel):
    """Structured response for market regime detection."""
    regime: MarketRegime = Field(
        ..., 
        description="Current market regime: TRENDING_UP, TRENDING_DOWN, or CHOPPY"
    )
    confidence: float = Field(
        ..., 
        ge=0.0, 
        le=1.0, 
        description="Confidence in regime assessment"
    )
    nifty_trend: str = Field(
        ..., 
        description="Brief description of Nifty 50 trend"
    )
    volatility_level: str = Field(
        default="NORMAL", 
        description="Volatility: LOW, NORMAL, HIGH"
    )
    recommended_position_size_multiplier: float = Field(
        default=1.0, 
        ge=0.0, 
        le=1.0, 
        description="Suggested position size multiplier (1.0 = full, 0.5 = half)"
    )
    reasoning: str = Field(
        ..., 
        description="Brief explanation of regime assessment"
    )
