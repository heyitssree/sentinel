"""
Trading Schedule Manager for The Sentinel.
Implements time-gated trading phases for Indian equity markets (NSE).

Phases:
- OBSERVATION (9:15 - 9:45 AM): Data ingestion only, no trading
- ACTIVE (9:45 AM - 2:45 PM): Full trading enabled
- SQUAREOFF (2:45 - 3:15 PM): Exit all positions, no new entries
- POSTMARKET (3:30 PM+): Generate daily report, analysis
"""
from datetime import datetime, time as dt_time, timedelta
from enum import Enum
from typing import Optional, Tuple, Callable
from dataclasses import dataclass
import logging
import os

logger = logging.getLogger(__name__)


class TradingPhase(Enum):
    """Trading session phases."""
    PREMARKET = "PREMARKET"       # Before 9:15 AM
    OBSERVATION = "OBSERVATION"   # 9:15 - 9:45 AM (ingestion only)
    ACTIVE = "ACTIVE"             # 9:45 AM - 2:45 PM (full trading)
    SQUAREOFF = "SQUAREOFF"       # 2:45 - 3:15 PM (exit only)
    POSTMARKET = "POSTMARKET"     # 3:30 PM+ (analysis)
    CLOSED = "CLOSED"             # Weekend / holidays


@dataclass
class PhaseSchedule:
    """Schedule configuration for a trading phase."""
    phase: TradingPhase
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    
    @property
    def start_time(self) -> dt_time:
        return dt_time(self.start_hour, self.start_minute)
    
    @property
    def end_time(self) -> dt_time:
        return dt_time(self.end_hour, self.end_minute)
    
    def contains(self, t: dt_time) -> bool:
        """Check if a time falls within this phase."""
        return self.start_time <= t < self.end_time


class TradingPhaseManager:
    """
    Manages trading phases based on NSE market hours.
    
    Usage:
        manager = TradingPhaseManager()
        phase = manager.get_current_phase()
        
        if manager.can_open_new_positions():
            # Execute entry logic
        
        if manager.should_force_close():
            # Close all positions
    """
    
    # Default schedule (IST)
    DEFAULT_SCHEDULES = [
        PhaseSchedule(TradingPhase.PREMARKET, 0, 0, 9, 15),
        PhaseSchedule(TradingPhase.OBSERVATION, 9, 15, 9, 45),
        PhaseSchedule(TradingPhase.ACTIVE, 9, 45, 14, 45),
        PhaseSchedule(TradingPhase.SQUAREOFF, 14, 45, 15, 15),
        PhaseSchedule(TradingPhase.POSTMARKET, 15, 30, 23, 59),
    ]
    
    def __init__(
        self,
        observation_start: str = None,
        observation_end: str = None,
        active_end: str = None,
        squareoff_end: str = None,
        postmarket_start: str = None
    ):
        """
        Initialize the phase manager with optional custom times.
        
        Times can be overridden via environment variables:
        - OBSERVATION_START (default: 09:15)
        - OBSERVATION_END (default: 09:45)
        - ACTIVE_TRADING_END (default: 14:45)
        - SQUARE_OFF_END (default: 15:15)
        - POST_MARKET_START (default: 15:30)
        """
        # Parse times from env or use defaults
        obs_start = self._parse_time(
            observation_start or os.getenv("OBSERVATION_START", "09:15")
        )
        obs_end = self._parse_time(
            observation_end or os.getenv("OBSERVATION_END", "09:45")
        )
        active_end_t = self._parse_time(
            active_end or os.getenv("ACTIVE_TRADING_END", "14:45")
        )
        squareoff_end_t = self._parse_time(
            squareoff_end or os.getenv("SQUARE_OFF_END", "15:15")
        )
        postmarket_start_t = self._parse_time(
            postmarket_start or os.getenv("POST_MARKET_START", "15:30")
        )
        
        # Build custom schedule
        self.schedules = [
            PhaseSchedule(TradingPhase.PREMARKET, 0, 0, obs_start.hour, obs_start.minute),
            PhaseSchedule(TradingPhase.OBSERVATION, obs_start.hour, obs_start.minute, 
                         obs_end.hour, obs_end.minute),
            PhaseSchedule(TradingPhase.ACTIVE, obs_end.hour, obs_end.minute,
                         active_end_t.hour, active_end_t.minute),
            PhaseSchedule(TradingPhase.SQUAREOFF, active_end_t.hour, active_end_t.minute,
                         squareoff_end_t.hour, squareoff_end_t.minute),
            PhaseSchedule(TradingPhase.POSTMARKET, postmarket_start_t.hour, postmarket_start_t.minute,
                         23, 59),
        ]
        
        # Callbacks for phase transitions
        self._on_phase_change: Optional[Callable[[TradingPhase, TradingPhase], None]] = None
        self._last_phase: Optional[TradingPhase] = None
        
        logger.info(
            f"TradingPhaseManager initialized: "
            f"OBS={obs_start}-{obs_end}, ACTIVE until {active_end_t}, "
            f"SQUAREOFF until {squareoff_end_t}"
        )
    
    @staticmethod
    def _parse_time(time_str: str) -> dt_time:
        """Parse HH:MM string to time object."""
        try:
            parts = time_str.split(":")
            return dt_time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            logger.warning(f"Invalid time format: {time_str}, using 09:15")
            return dt_time(9, 15)
    
    def get_current_phase(self, now: datetime = None) -> TradingPhase:
        """
        Get the current trading phase.
        
        Args:
            now: Optional datetime for testing (default: current time)
            
        Returns:
            Current TradingPhase
        """
        if now is None:
            now = datetime.now()
        
        # Check for weekend
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return TradingPhase.CLOSED
        
        current_time = now.time()
        
        for schedule in self.schedules:
            if schedule.contains(current_time):
                phase = schedule.phase
                
                # Trigger callback on phase change
                if self._on_phase_change and phase != self._last_phase:
                    if self._last_phase is not None:
                        self._on_phase_change(self._last_phase, phase)
                    self._last_phase = phase
                
                return phase
        
        return TradingPhase.CLOSED
    
    def can_open_new_positions(self, now: datetime = None) -> bool:
        """
        Check if new positions can be opened.
        Only allowed during ACTIVE phase.
        """
        return self.get_current_phase(now) == TradingPhase.ACTIVE
    
    def can_trade(self, now: datetime = None) -> bool:
        """
        Check if any trading activity is allowed.
        Allowed during ACTIVE and SQUAREOFF phases.
        """
        phase = self.get_current_phase(now)
        return phase in [TradingPhase.ACTIVE, TradingPhase.SQUAREOFF]
    
    def should_force_close(self, now: datetime = None) -> bool:
        """
        Check if positions should be forcibly closed.
        True during SQUAREOFF phase.
        """
        return self.get_current_phase(now) == TradingPhase.SQUAREOFF
    
    def is_observation_phase(self, now: datetime = None) -> bool:
        """Check if we're in observation (ingestion only) phase."""
        return self.get_current_phase(now) == TradingPhase.OBSERVATION
    
    def is_postmarket(self, now: datetime = None) -> bool:
        """Check if market is in post-market analysis phase."""
        return self.get_current_phase(now) == TradingPhase.POSTMARKET
    
    def should_run_daily_report(self, now: datetime = None) -> bool:
        """
        Check if daily report should be generated.
        True at 3:30 PM (start of POSTMARKET).
        """
        if now is None:
            now = datetime.now()
        
        if now.weekday() >= 5:
            return False
        
        # Check if we just entered POSTMARKET (within first 5 minutes)
        postmarket_schedule = self.schedules[4]  # POSTMARKET
        postmarket_start = datetime.combine(now.date(), postmarket_schedule.start_time)
        
        return postmarket_start <= now < postmarket_start + timedelta(minutes=5)
    
    def time_until_phase(self, target_phase: TradingPhase, now: datetime = None) -> int:
        """
        Get seconds until a specific phase starts.
        
        Args:
            target_phase: The phase to wait for
            now: Optional datetime for testing
            
        Returns:
            Seconds until phase starts, or 0 if already in that phase
        """
        if now is None:
            now = datetime.now()
        
        current_phase = self.get_current_phase(now)
        if current_phase == target_phase:
            return 0
        
        # Find the target phase schedule
        for schedule in self.schedules:
            if schedule.phase == target_phase:
                target_start = datetime.combine(now.date(), schedule.start_time)
                
                # If target time has passed today, it's tomorrow
                if target_start <= now:
                    target_start += timedelta(days=1)
                
                return int((target_start - now).total_seconds())
        
        return 0
    
    def get_phase_info(self, now: datetime = None) -> dict:
        """
        Get comprehensive phase information for API/UI.
        
        Returns:
            Dict with current phase, timing info, and capabilities
        """
        if now is None:
            now = datetime.now()
        
        phase = self.get_current_phase(now)
        
        # Find current and next phase schedules
        current_schedule = None
        next_schedule = None
        
        for i, schedule in enumerate(self.schedules):
            if schedule.phase == phase:
                current_schedule = schedule
                if i + 1 < len(self.schedules):
                    next_schedule = self.schedules[i + 1]
                break
        
        info = {
            'phase': phase.value,
            'phase_name': self._get_phase_display_name(phase),
            'is_weekend': now.weekday() >= 5,
            'current_time': now.strftime("%H:%M:%S"),
            'can_open_positions': self.can_open_new_positions(now),
            'can_trade': self.can_trade(now),
            'should_close_all': self.should_force_close(now),
            'is_postmarket': self.is_postmarket(now),
        }
        
        if current_schedule:
            info['phase_start'] = current_schedule.start_time.strftime("%H:%M")
            info['phase_end'] = current_schedule.end_time.strftime("%H:%M")
            
            # Time remaining in current phase
            phase_end = datetime.combine(now.date(), current_schedule.end_time)
            if phase_end > now:
                remaining = (phase_end - now).total_seconds()
                info['phase_remaining_seconds'] = int(remaining)
                info['phase_remaining'] = self._format_duration(remaining)
        
        if next_schedule:
            info['next_phase'] = next_schedule.phase.value
            info['next_phase_start'] = next_schedule.start_time.strftime("%H:%M")
        
        return info
    
    @staticmethod
    def _get_phase_display_name(phase: TradingPhase) -> str:
        """Get human-readable phase name."""
        names = {
            TradingPhase.PREMARKET: "Pre-Market",
            TradingPhase.OBSERVATION: "Observation (No Trading)",
            TradingPhase.ACTIVE: "Active Trading",
            TradingPhase.SQUAREOFF: "Square-Off (Exit Only)",
            TradingPhase.POSTMARKET: "Post-Market Analysis",
            TradingPhase.CLOSED: "Market Closed",
        }
        return names.get(phase, phase.value)
    
    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format seconds as HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"
    
    def set_phase_change_callback(self, callback: Callable[[TradingPhase, TradingPhase], None]):
        """
        Set a callback to be triggered on phase transitions.
        
        Args:
            callback: Function(old_phase, new_phase) to call on transitions
        """
        self._on_phase_change = callback
    
    def get_schedule_summary(self) -> str:
        """Get a formatted summary of the trading schedule."""
        lines = ["Trading Schedule (IST):"]
        for schedule in self.schedules:
            lines.append(
                f"  {schedule.phase.value}: "
                f"{schedule.start_time.strftime('%H:%M')} - "
                f"{schedule.end_time.strftime('%H:%M')}"
            )
        return "\n".join(lines)


# Singleton instance
_phase_manager: Optional[TradingPhaseManager] = None


def get_phase_manager() -> TradingPhaseManager:
    """Get or create the phase manager singleton."""
    global _phase_manager
    if _phase_manager is None:
        _phase_manager = TradingPhaseManager()
    return _phase_manager
