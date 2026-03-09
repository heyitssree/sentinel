"""
Trading Scheduler for The Sentinel.

Implements time-gated trading phases:
- 9:15 - 9:45 AM: Observation Phase (data ingestion only, no trades)
- 9:45 - 2:45 PM: Active Trading Phase (full trading enabled)
- 2:45 - 3:15 PM: Square-off Phase (exit all, no new entries)
- 3:30 PM+: Post-Market Analysis (Gemini daily report)
"""
from datetime import datetime, time as dt_time, timedelta
from enum import Enum
from typing import Tuple, Callable, Optional
import logging

logger = logging.getLogger(__name__)


class TradingPhase(Enum):
    """Trading phase definitions."""
    PRE_MARKET = "PRE_MARKET"           # Before 9:15 AM
    OBSERVATION = "OBSERVATION"          # 9:15 - 9:45 AM
    ACTIVE_TRADING = "ACTIVE_TRADING"    # 9:45 AM - 2:45 PM
    SQUARE_OFF = "SQUARE_OFF"            # 2:45 - 3:15 PM
    POST_MARKET = "POST_MARKET"          # 3:30 PM+
    MARKET_CLOSED = "MARKET_CLOSED"      # Weekends/Holidays


class TradingScheduler:
    """
    Manages time-gated trading phases.
    
    Each phase has specific rules:
    - OBSERVATION: Data ingestion only, no trade execution
    - ACTIVE_TRADING: Full trading enabled with confluence checks
    - SQUARE_OFF: Exit all positions, no new entries
    - POST_MARKET: Generate daily report, prepare for next day
    """
    
    def __init__(
        self,
        observation_start: dt_time = dt_time(9, 15),
        observation_end: dt_time = dt_time(9, 45),
        active_end: dt_time = dt_time(14, 45),
        square_off_end: dt_time = dt_time(15, 15),
        post_market_start: dt_time = dt_time(15, 30),
        on_phase_change: Callable[[TradingPhase, TradingPhase], None] = None
    ):
        """
        Initialize the trading scheduler.
        
        Args:
            observation_start: Start of observation phase (default 9:15)
            observation_end: End of observation phase (default 9:45)
            active_end: End of active trading (default 14:45)
            square_off_end: End of square-off phase (default 15:15)
            post_market_start: Start of post-market analysis (default 15:30)
            on_phase_change: Callback when phase changes
        """
        self.observation_start = observation_start
        self.observation_end = observation_end
        self.active_end = active_end
        self.square_off_end = square_off_end
        self.post_market_start = post_market_start
        
        self._on_phase_change = on_phase_change
        self._current_phase: Optional[TradingPhase] = None
        self._last_check: Optional[datetime] = None
        self._daily_report_generated = False
        
        logger.info(
            f"TradingScheduler initialized: "
            f"Observation {observation_start}-{observation_end}, "
            f"Active until {active_end}, Square-off until {square_off_end}"
        )
    
    def get_current_phase(self, now: datetime = None) -> TradingPhase:
        """
        Determine the current trading phase.
        
        Args:
            now: Current datetime (default: now)
            
        Returns:
            Current TradingPhase
        """
        if now is None:
            now = datetime.now()
        
        # Check weekend
        if now.weekday() >= 5:
            return TradingPhase.MARKET_CLOSED
        
        current_time = now.time()
        
        # Pre-market
        if current_time < self.observation_start:
            return TradingPhase.PRE_MARKET
        
        # Observation phase (9:15 - 9:45)
        if self.observation_start <= current_time < self.observation_end:
            return TradingPhase.OBSERVATION
        
        # Active trading (9:45 - 14:45)
        if self.observation_end <= current_time < self.active_end:
            return TradingPhase.ACTIVE_TRADING
        
        # Square-off phase (14:45 - 15:15)
        if self.active_end <= current_time < self.square_off_end:
            return TradingPhase.SQUARE_OFF
        
        # Post-market (15:30+)
        if current_time >= self.post_market_start:
            return TradingPhase.POST_MARKET
        
        # Gap between square-off end and post-market start
        if self.square_off_end <= current_time < self.post_market_start:
            return TradingPhase.SQUARE_OFF  # Continue square-off
        
        return TradingPhase.MARKET_CLOSED
    
    def check_phase_change(self) -> Tuple[bool, Optional[TradingPhase], Optional[TradingPhase]]:
        """
        Check if trading phase has changed.
        
        Returns:
            Tuple of (changed, old_phase, new_phase)
        """
        new_phase = self.get_current_phase()
        
        if self._current_phase != new_phase:
            old_phase = self._current_phase
            self._current_phase = new_phase
            
            logger.info(f"📅 Phase change: {old_phase} → {new_phase}")
            
            # Reset daily report flag at start of day
            if new_phase == TradingPhase.PRE_MARKET:
                self._daily_report_generated = False
            
            # Trigger callback
            if self._on_phase_change and old_phase is not None:
                try:
                    self._on_phase_change(old_phase, new_phase)
                except Exception as e:
                    logger.error(f"Phase change callback error: {e}")
            
            return True, old_phase, new_phase
        
        return False, None, None
    
    def can_enter_trade(self) -> Tuple[bool, str]:
        """
        Check if new trade entries are allowed.
        
        Returns:
            Tuple of (can_enter, reason)
        """
        phase = self.get_current_phase()
        
        if phase == TradingPhase.ACTIVE_TRADING:
            return True, "Active trading phase"
        
        if phase == TradingPhase.OBSERVATION:
            return False, "Observation phase - data ingestion only"
        
        if phase == TradingPhase.SQUARE_OFF:
            return False, "Square-off phase - no new entries"
        
        if phase == TradingPhase.PRE_MARKET:
            return False, "Pre-market - market not open"
        
        if phase == TradingPhase.POST_MARKET:
            return False, "Post-market - market closed"
        
        return False, "Market closed"
    
    def can_exit_trade(self) -> Tuple[bool, str]:
        """
        Check if trade exits are allowed.
        
        Returns:
            Tuple of (can_exit, reason)
        """
        phase = self.get_current_phase()
        
        if phase in [TradingPhase.ACTIVE_TRADING, TradingPhase.SQUARE_OFF]:
            return True, f"{phase.value} - exits allowed"
        
        if phase == TradingPhase.OBSERVATION:
            # Allow exits during observation for emergency
            return True, "Observation phase - emergency exits allowed"
        
        return False, "Market not open for exits"
    
    def should_square_off(self) -> bool:
        """Check if we should square off all positions."""
        return self.get_current_phase() == TradingPhase.SQUARE_OFF
    
    def should_generate_report(self) -> bool:
        """Check if we should generate daily report."""
        if self._daily_report_generated:
            return False
        return self.get_current_phase() == TradingPhase.POST_MARKET
    
    def mark_report_generated(self):
        """Mark that daily report has been generated."""
        self._daily_report_generated = True
        logger.info("Daily report marked as generated")
    
    def get_time_until_next_phase(self) -> Tuple[TradingPhase, int]:
        """
        Get the next phase and seconds until it starts.
        
        Returns:
            Tuple of (next_phase, seconds_until)
        """
        now = datetime.now()
        current_phase = self.get_current_phase()
        today = now.date()
        
        phase_times = [
            (TradingPhase.OBSERVATION, self.observation_start),
            (TradingPhase.ACTIVE_TRADING, self.observation_end),
            (TradingPhase.SQUARE_OFF, self.active_end),
            (TradingPhase.POST_MARKET, self.post_market_start),
        ]
        
        for next_phase, phase_start in phase_times:
            phase_datetime = datetime.combine(today, phase_start)
            if now < phase_datetime:
                seconds = int((phase_datetime - now).total_seconds())
                return next_phase, seconds
        
        # Next trading day
        if current_phase in [TradingPhase.POST_MARKET, TradingPhase.MARKET_CLOSED]:
            # Calculate next market open
            next_day = now + timedelta(days=1)
            while next_day.weekday() >= 5:  # Skip weekends
                next_day += timedelta(days=1)
            next_open = datetime.combine(next_day.date(), self.observation_start)
            seconds = int((next_open - now).total_seconds())
            return TradingPhase.OBSERVATION, seconds
        
        return TradingPhase.MARKET_CLOSED, 0
    
    def get_phase_info(self) -> dict:
        """Get current phase information."""
        phase = self.get_current_phase()
        can_enter, enter_reason = self.can_enter_trade()
        can_exit, exit_reason = self.can_exit_trade()
        next_phase, seconds_until = self.get_time_until_next_phase()
        
        return {
            "current_phase": phase.value,
            "can_enter_trade": can_enter,
            "enter_reason": enter_reason,
            "can_exit_trade": can_exit,
            "exit_reason": exit_reason,
            "should_square_off": self.should_square_off(),
            "next_phase": next_phase.value,
            "seconds_until_next": seconds_until,
            "minutes_until_next": seconds_until // 60,
            "daily_report_pending": self.should_generate_report(),
        }
    
    def get_phase_schedule(self) -> dict:
        """Get the full phase schedule."""
        return {
            "observation": {
                "start": self.observation_start.strftime("%H:%M"),
                "end": self.observation_end.strftime("%H:%M"),
                "description": "Data ingestion only, no trades"
            },
            "active_trading": {
                "start": self.observation_end.strftime("%H:%M"),
                "end": self.active_end.strftime("%H:%M"),
                "description": "Full trading enabled"
            },
            "square_off": {
                "start": self.active_end.strftime("%H:%M"),
                "end": self.square_off_end.strftime("%H:%M"),
                "description": "Exit all positions, no new entries"
            },
            "post_market": {
                "start": self.post_market_start.strftime("%H:%M"),
                "end": "EOD",
                "description": "Generate daily report"
            }
        }


def format_phase_status(phase: TradingPhase) -> str:
    """Format phase for display."""
    icons = {
        TradingPhase.PRE_MARKET: "🌅",
        TradingPhase.OBSERVATION: "👀",
        TradingPhase.ACTIVE_TRADING: "🚀",
        TradingPhase.SQUARE_OFF: "⏹️",
        TradingPhase.POST_MARKET: "📊",
        TradingPhase.MARKET_CLOSED: "🌙",
    }
    return f"{icons.get(phase, '❓')} {phase.value}"
