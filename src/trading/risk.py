"""
Risk Management Module for The Sentinel.
Implements kill switch, rate limiting, and compliance controls.

HYBRID KILL SWITCH:
- Hard-coded safety ceiling (3%) in .env - AI cannot override
- User-configurable limit via UI (e.g., 2%)
- System enforces the LOWER of the two limits

REGIME INTEGRATION:
- When CHOPPY regime detected, kill switch limit reduced by 50%
- Prevents "death by a thousand cuts" in sideways markets
"""
from datetime import datetime, time as dt_time
from typing import Optional, Callable, TYPE_CHECKING
import threading
import time
import logging
import os
from dataclasses import dataclass
from collections import deque

if TYPE_CHECKING:
    from src.gemini.regime_detector import RegimeState

logger = logging.getLogger(__name__)

# Safety ceiling - HARD-CODED, cannot be changed by AI or UI
# Load from environment, default to 3% of capital
MTM_LOSS_CEILING = float(os.getenv("MTM_LOSS_CEILING", "0.03"))


@dataclass
class RiskState:
    """Current risk state of the system."""
    is_active: bool
    kill_switch_triggered: bool
    current_mtm_loss: float
    orders_this_second: int
    is_market_hours: bool
    reason: str = ""


class HybridKillSwitch:
    """
    Hybrid circuit breaker with safety ceiling and user limit.
    
    CRITICAL SAFETY DESIGN:
    - Safety ceiling: Hard-coded from .env (default 3% of capital)
    - User limit: Configurable via UI (e.g., 2% of capital)
    - System enforces: min(ceiling, user_limit)
    
    The safety ceiling CANNOT be overridden by AI or user actions.
    This is the last line of defense against catastrophic losses.
    """
    
    def __init__(
        self,
        starting_capital: float,
        user_limit_percent: float = 0.02,  # Default 2%
        on_trigger: Callable = None
    ):
        """
        Initialize the hybrid kill switch.
        
        Args:
            starting_capital: Total portfolio capital for % calculations
            user_limit_percent: User-configurable limit as decimal (0.02 = 2%)
            on_trigger: Callback function when kill switch triggers
        """
        self._starting_capital = starting_capital
        
        # SAFETY CEILING - from .env, cannot be changed programmatically
        self._ceiling_percent = MTM_LOSS_CEILING
        self._ceiling_amount = starting_capital * self._ceiling_percent
        
        # User limit - can be adjusted via UI
        self._user_limit_percent = min(user_limit_percent, self._ceiling_percent)
        self._user_limit_amount = starting_capital * self._user_limit_percent
        
        # Effective limit is the LOWER of ceiling and user limit
        self._effective_limit = min(self._ceiling_amount, self._user_limit_amount)
        
        self._triggered = False
        self._trigger_time: Optional[datetime] = None
        self._trigger_reason: str = ""
        self._on_trigger = on_trigger
        self._lock = threading.Lock()
        self._disabled_for_day = False
        self._disabled_date: Optional[datetime] = None
        
        # Regime-based multiplier (1.0 = full limit, 0.5 = half for CHOPPY)
        self._regime_multiplier = 1.0
        self._regime_adjusted_limit = self._effective_limit
        
        logger.info(
            f"HybridKillSwitch initialized: "
            f"ceiling={self._ceiling_percent*100:.1f}% (₹{self._ceiling_amount:,.0f}), "
            f"user_limit={self._user_limit_percent*100:.1f}% (₹{self._user_limit_amount:,.0f}), "
            f"effective=₹{self._effective_limit:,.0f}"
        )
    
    @property
    def limit(self) -> float:
        """Get the effective MTM loss limit (regime-adjusted, read-only)."""
        return self._regime_adjusted_limit
    
    @property
    def base_limit(self) -> float:
        """Get the base effective limit before regime adjustment."""
        return self._effective_limit
    
    @property
    def regime_multiplier(self) -> float:
        """Get the current regime multiplier."""
        return self._regime_multiplier
    
    @property
    def ceiling(self) -> float:
        """Get the safety ceiling (read-only, from .env)."""
        return self._ceiling_amount
    
    @property
    def user_limit(self) -> float:
        """Get the user-configured limit."""
        return self._user_limit_amount
    
    @property
    def is_triggered(self) -> bool:
        """Check if kill switch has been triggered."""
        return self._triggered
    
    @property
    def is_disabled_for_day(self) -> bool:
        """Check if trading is disabled for the day."""
        if not self._disabled_for_day:
            return False
        # Reset at midnight
        if self._disabled_date and self._disabled_date.date() != datetime.now().date():
            self._disabled_for_day = False
            self._disabled_date = None
            return False
        return True
    
    def set_user_limit(self, limit_percent: float) -> bool:
        """
        Set user-configurable limit (cannot exceed ceiling).
        
        Args:
            limit_percent: New limit as decimal (e.g., 0.02 for 2%)
            
        Returns:
            True if limit was set, False if it exceeded ceiling
        """
        with self._lock:
            if limit_percent > self._ceiling_percent:
                logger.warning(
                    f"User limit {limit_percent*100:.1f}% exceeds ceiling "
                    f"{self._ceiling_percent*100:.1f}% - using ceiling"
                )
                limit_percent = self._ceiling_percent
            
            self._user_limit_percent = limit_percent
            self._user_limit_amount = self._starting_capital * limit_percent
            self._effective_limit = min(self._ceiling_amount, self._user_limit_amount)
            self._regime_adjusted_limit = self._effective_limit * self._regime_multiplier
            
            logger.info(f"User limit updated to {limit_percent*100:.1f}% (₹{self._user_limit_amount:,.0f})")
            return True
    
    def apply_regime_multiplier(self, multiplier: float, regime_name: str = ""):
        """
        Apply regime-based multiplier to the kill switch limit.
        
        When CHOPPY regime detected, multiplier = 0.5 to tighten the limit
        and prevent "death by a thousand cuts" in sideways markets.
        
        Args:
            multiplier: Multiplier to apply (0.5 = half limit, 1.0 = full)
            regime_name: Name of the regime for logging
        """
        with self._lock:
            old_multiplier = self._regime_multiplier
            self._regime_multiplier = max(0.1, min(1.0, multiplier))  # Clamp 0.1-1.0
            self._regime_adjusted_limit = self._effective_limit * self._regime_multiplier
            
            if old_multiplier != self._regime_multiplier:
                logger.info(
                    f"Kill switch limit adjusted for {regime_name} regime: "
                    f"₹{self._effective_limit:,.0f} × {self._regime_multiplier:.0%} = "
                    f"₹{self._regime_adjusted_limit:,.0f}"
                )
    
    def reset_regime_multiplier(self):
        """Reset regime multiplier to 1.0 (full limit)."""
        with self._lock:
            self._regime_multiplier = 1.0
            self._regime_adjusted_limit = self._effective_limit
            logger.info(f"Kill switch regime multiplier reset to 1.0")
    
    def check(self, current_mtm_loss: float) -> bool:
        """
        Check if MTM loss exceeds limit and trigger if necessary.
        
        Uses regime-adjusted limit (tighter in CHOPPY markets).
        
        Args:
            current_mtm_loss: Current mark-to-market loss (positive = loss)
            
        Returns:
            True if trading can continue, False if kill switch triggered
        """
        with self._lock:
            if self._triggered or self._disabled_for_day:
                return False
            
            # Use regime-adjusted limit
            if current_mtm_loss >= self._regime_adjusted_limit:
                regime_note = ""
                if self._regime_multiplier < 1.0:
                    regime_note = f" [REGIME: {self._regime_multiplier:.0%} of base]"
                
                self._trigger(
                    f"MTM loss ₹{current_mtm_loss:,.2f} exceeded limit "
                    f"₹{self._regime_adjusted_limit:,.2f}{regime_note}"
                )
                return False
            
            return True
    
    def _trigger(self, reason: str):
        """Trigger the kill switch."""
        self._triggered = True
        self._trigger_time = datetime.now()
        self._trigger_reason = reason
        self._disabled_for_day = True
        self._disabled_date = datetime.now()
        
        logger.critical(f"🚨 KILL SWITCH TRIGGERED: {reason}")
        logger.critical(f"⏰ Trigger time: {self._trigger_time}")
        logger.critical("🛑 ALL TRADING HALTED - Manual intervention required")
        logger.critical("📅 Trading disabled for rest of day")
        
        if self._on_trigger:
            try:
                self._on_trigger(reason)
            except Exception as e:
                logger.error(f"Kill switch callback error: {e}")
    
    def disable_trading_for_day(self, reason: str = "Manual disable"):
        """Disable all trading for the rest of the day."""
        with self._lock:
            self._disabled_for_day = True
            self._disabled_date = datetime.now()
            self._trigger_reason = reason
            logger.warning(f"Trading disabled for day: {reason}")
    
    def manual_trigger(self, reason: str = "Manual trigger"):
        """Manually trigger the kill switch."""
        with self._lock:
            self._trigger(reason)
    
    def reset(self, confirmation: str):
        """
        Reset the kill switch (requires confirmation string).
        
        Args:
            confirmation: Must be "CONFIRM_RESET" to reset
        """
        if confirmation != "CONFIRM_RESET":
            logger.warning("Kill switch reset rejected - invalid confirmation")
            return False
        
        with self._lock:
            self._triggered = False
            self._trigger_time = None
            self._trigger_reason = ""
            self._disabled_for_day = False
            self._disabled_date = None
            logger.info("Kill switch reset by operator")
            return True
    
    def get_status(self) -> dict:
        """Get kill switch status."""
        return {
            'triggered': self._triggered,
            'disabled_for_day': self._disabled_for_day,
            'trigger_time': self._trigger_time,
            'trigger_reason': self._trigger_reason,
            'ceiling_percent': self._ceiling_percent,
            'ceiling_amount': self._ceiling_amount,
            'user_limit_percent': self._user_limit_percent,
            'user_limit_amount': self._user_limit_amount,
            'effective_limit': self._effective_limit,
            'regime_multiplier': self._regime_multiplier,
            'regime_adjusted_limit': self._regime_adjusted_limit,
        }


# Keep legacy KillSwitch for backward compatibility
class KillSwitch(HybridKillSwitch):
    """Legacy alias for HybridKillSwitch."""
    
    def __init__(self, mtm_loss_limit: float = 5000.0, on_trigger: Callable = None):
        # Convert absolute limit to a percentage-based system
        # Assume 100k capital for backward compatibility
        super().__init__(
            starting_capital=100000.0,
            user_limit_percent=mtm_loss_limit / 100000.0,
            on_trigger=on_trigger
        )


class RateLimiter:
    """
    Rate limiter to enforce SEBI's 10 orders per second limit.
    Uses token bucket algorithm.
    """
    
    def __init__(self, max_orders_per_second: int = 10):
        """
        Initialize the rate limiter.
        
        Args:
            max_orders_per_second: Maximum orders allowed per second
        """
        self.max_ops = max_orders_per_second
        self._timestamps: deque = deque(maxlen=max_orders_per_second)
        self._lock = threading.Lock()
        
        logger.info(f"Rate limiter initialized: {max_orders_per_second} OPS")
    
    def can_place_order(self) -> bool:
        """
        Check if we can place an order without exceeding rate limit.
        
        Returns:
            True if order can be placed, False otherwise
        """
        with self._lock:
            now = time.time()
            
            # Remove timestamps older than 1 second
            while self._timestamps and now - self._timestamps[0] > 1.0:
                self._timestamps.popleft()
            
            return len(self._timestamps) < self.max_ops
    
    def record_order(self):
        """Record that an order was placed."""
        with self._lock:
            self._timestamps.append(time.time())
    
    def wait_if_needed(self) -> float:
        """
        Wait if necessary to respect rate limit.
        
        Returns:
            Time waited in seconds
        """
        waited = 0.0
        
        while not self.can_place_order():
            time.sleep(0.1)
            waited += 0.1
            
            if waited > 5.0:  # Safety timeout
                logger.warning("Rate limiter timeout - resetting")
                with self._lock:
                    self._timestamps.clear()
                break
        
        return waited
    
    def get_current_rate(self) -> int:
        """Get current orders in the last second."""
        with self._lock:
            now = time.time()
            while self._timestamps and now - self._timestamps[0] > 1.0:
                self._timestamps.popleft()
            return len(self._timestamps)


class MarketHoursGuard:
    """
    Ensures trading only occurs during market hours.
    Indian market hours: 9:15 AM - 3:30 PM IST
    """
    
    def __init__(self, 
                 open_hour: int = 9, open_minute: int = 15,
                 close_hour: int = 15, close_minute: int = 30):
        """
        Initialize market hours guard.
        
        Args:
            open_hour: Market open hour (default 9)
            open_minute: Market open minute (default 15)
            close_hour: Market close hour (default 15)
            close_minute: Market close minute (default 30)
        """
        self.market_open = dt_time(open_hour, open_minute)
        self.market_close = dt_time(close_hour, close_minute)
        
        logger.info(f"Market hours: {self.market_open} - {self.market_close} IST")
    
    def is_market_open(self, now: datetime = None) -> bool:
        """
        Check if market is currently open.
        
        Args:
            now: Current datetime (default: now)
            
        Returns:
            True if market is open
        """
        if now is None:
            now = datetime.now()
        
        current_time = now.time()
        
        # Check if it's a weekend
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False
        
        return self.market_open <= current_time <= self.market_close
    
    def is_closing_time(self, buffer_minutes: int = 5) -> bool:
        """
        Check if it's near market close (time to square off).
        
        Args:
            buffer_minutes: Minutes before close to trigger
            
        Returns:
            True if within closing buffer
        """
        now = datetime.now()
        close_time = datetime.combine(now.date(), self.market_close)
        buffer_time = close_time.replace(
            minute=close_time.minute - buffer_minutes
        )
        
        return now.time() >= buffer_time.time()
    
    def time_to_close(self) -> int:
        """Get seconds until market close."""
        now = datetime.now()
        close_time = datetime.combine(now.date(), self.market_close)
        
        if now > close_time:
            return 0
        
        return int((close_time - now).total_seconds())
    
    def time_to_open(self) -> int:
        """Get seconds until market open."""
        now = datetime.now()
        open_time = datetime.combine(now.date(), self.market_open)
        
        if now.time() >= self.market_open:
            # Market already open or passed
            return 0
        
        return int((open_time - now).total_seconds())


class RiskManager:
    """
    Unified risk management coordinator.
    Combines kill switch, rate limiter, and market hours guard.
    """
    
    def __init__(self, mtm_loss_limit: float = 5000.0,
                 max_orders_per_second: int = 10,
                 on_kill_switch: Callable = None):
        """
        Initialize the risk manager.
        
        Args:
            mtm_loss_limit: MTM loss limit for kill switch
            max_orders_per_second: Rate limit
            on_kill_switch: Callback when kill switch triggers
        """
        self.kill_switch = KillSwitch(mtm_loss_limit, on_kill_switch)
        self.rate_limiter = RateLimiter(max_orders_per_second)
        self.market_hours = MarketHoursGuard()
        
        self._is_active = True
    
    def can_trade(self, mtm_loss: float = 0.0) -> tuple:
        """
        Check if trading is allowed.
        
        Args:
            mtm_loss: Current MTM loss
            
        Returns:
            Tuple of (can_trade, reason)
        """
        # Check kill switch
        if self.kill_switch.is_triggered:
            return False, "Kill switch triggered"
        
        # Check MTM
        if not self.kill_switch.check(mtm_loss):
            return False, f"MTM loss exceeded: ₹{mtm_loss:.2f}"
        
        # Check market hours
        if not self.market_hours.is_market_open():
            return False, "Market is closed"
        
        # Check rate limit
        if not self.rate_limiter.can_place_order():
            return False, "Rate limit reached"
        
        return True, "OK"
    
    def pre_order_check(self, mtm_loss: float = 0.0) -> bool:
        """
        Perform pre-order risk checks.
        Call this before every order.
        
        Returns:
            True if order can proceed
        """
        can_trade, reason = self.can_trade(mtm_loss)
        
        if not can_trade:
            logger.warning(f"Order blocked: {reason}")
            return False
        
        # Wait for rate limit if needed
        waited = self.rate_limiter.wait_if_needed()
        if waited > 0:
            logger.debug(f"Waited {waited:.2f}s for rate limit")
        
        return True
    
    def post_order_record(self):
        """Record that an order was placed."""
        self.rate_limiter.record_order()
    
    def get_state(self, mtm_loss: float = 0.0) -> RiskState:
        """Get current risk state."""
        return RiskState(
            is_active=self._is_active,
            kill_switch_triggered=self.kill_switch.is_triggered,
            current_mtm_loss=mtm_loss,
            orders_this_second=self.rate_limiter.get_current_rate(),
            is_market_hours=self.market_hours.is_market_open(),
            reason="" if not self.kill_switch.is_triggered else self.kill_switch._trigger_reason
        )
    
    def emergency_stop(self, reason: str = "Emergency stop"):
        """Trigger emergency stop."""
        self.kill_switch.manual_trigger(reason)
        self._is_active = False
    
    def should_close_positions(self) -> bool:
        """Check if positions should be closed (end of day)."""
        return self.market_hours.is_closing_time()
