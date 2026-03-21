"""
Task 1: Unit Testing for Risk Management.

Validates the HybridKillSwitch in src/trading/risk.py:
- Hard-coded ceiling (MTM_LOSS_CEILING) cannot be overridden by set_user_limit
- apply_regime_multiplier correctly reduces effective loss limit
- Specific test case: MTM loss of 3000 with limit 5000, then CHOPPY regime (0.5x)
  -> engine halts because new limit is 2500
"""
import sys
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.trading.risk import (
    HybridKillSwitch,
    KillSwitch,
    RateLimiter,
    MarketHoursGuard,
    RiskManager,
    RiskState,
    MTM_LOSS_CEILING,
)


class TestHybridKillSwitchCeiling:
    """Test that the hard-coded ceiling cannot be overridden."""

    def test_ceiling_loaded_from_env(self):
        """MTM_LOSS_CEILING should be loaded from env (default 0.03 = 3%)."""
        assert MTM_LOSS_CEILING > 0
        assert MTM_LOSS_CEILING <= 1.0

    def test_ceiling_cannot_be_exceeded_by_user_limit(self):
        """set_user_limit should not allow exceeding the ceiling."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.02)

        # The ceiling is MTM_LOSS_CEILING (default 0.03 = 3%)
        ceiling_amount = 100_000 * MTM_LOSS_CEILING

        # Try to set user limit above ceiling
        ks.set_user_limit(0.10)  # 10% - way above 3% ceiling

        # The effective limit should still be capped at ceiling
        assert ks.limit <= ceiling_amount
        assert ks.user_limit <= ceiling_amount

    def test_user_limit_clamped_to_ceiling(self):
        """When user_limit_percent > ceiling, it should be clamped."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.05)

        # user_limit should be clamped to ceiling
        assert ks._user_limit_percent <= MTM_LOSS_CEILING

    def test_user_limit_below_ceiling_accepted(self):
        """When user_limit is below ceiling, it should be used as-is."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.01)

        # Effective limit should be 1% of 100k = 1000
        assert ks.base_limit == 1000.0

    def test_effective_limit_is_min_of_ceiling_and_user(self):
        """Effective limit should be min(ceiling, user_limit)."""
        capital = 100_000
        ks = HybridKillSwitch(starting_capital=capital, user_limit_percent=0.02)

        ceiling_amount = capital * MTM_LOSS_CEILING
        user_amount = capital * 0.02
        expected = min(ceiling_amount, user_amount)

        assert ks.base_limit == expected

    def test_ceiling_is_read_only(self):
        """The ceiling property should reflect the hard-coded value."""
        capital = 200_000
        ks = HybridKillSwitch(starting_capital=capital, user_limit_percent=0.02)

        assert ks.ceiling == capital * MTM_LOSS_CEILING

    def test_set_user_limit_returns_true(self):
        """set_user_limit should return True even when clamped."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.02)
        result = ks.set_user_limit(0.05)  # Above ceiling
        assert result is True

    def test_multiple_set_user_limit_calls(self):
        """Multiple calls to set_user_limit should all respect ceiling."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.01)

        # Set to 2%
        ks.set_user_limit(0.02)
        assert ks.base_limit == 2000.0

        # Set to 5% (above ceiling) - should clamp
        ks.set_user_limit(0.05)
        assert ks.base_limit <= 100_000 * MTM_LOSS_CEILING

        # Set back to 1%
        ks.set_user_limit(0.01)
        assert ks.base_limit == 1000.0


class TestRegimeMultiplier:
    """Test apply_regime_multiplier and its effect on loss limits."""

    def test_regime_multiplier_reduces_limit(self):
        """CHOPPY regime (0.5x) should halve the effective limit."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.02)

        # Base limit = min(3000, 2000) = 2000
        base = ks.base_limit

        ks.apply_regime_multiplier(0.5, "CHOPPY")

        assert ks.limit == base * 0.5
        assert ks.regime_multiplier == 0.5

    def test_regime_multiplier_clamped_minimum(self):
        """Regime multiplier should be clamped at minimum 0.1."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.02)

        ks.apply_regime_multiplier(0.0, "EXTREME")
        assert ks.regime_multiplier == 0.1

    def test_regime_multiplier_clamped_maximum(self):
        """Regime multiplier should be clamped at maximum 1.0."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.02)

        ks.apply_regime_multiplier(2.0, "TRENDING")
        assert ks.regime_multiplier == 1.0

    def test_reset_regime_multiplier(self):
        """reset_regime_multiplier should restore full limit."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.02)
        base = ks.base_limit

        ks.apply_regime_multiplier(0.5, "CHOPPY")
        assert ks.limit == base * 0.5

        ks.reset_regime_multiplier()
        assert ks.limit == base
        assert ks.regime_multiplier == 1.0

    def test_regime_multiplier_persists_across_user_limit_changes(self):
        """Regime multiplier should be reapplied when user limit changes."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.02)

        ks.apply_regime_multiplier(0.5, "CHOPPY")

        # Change user limit
        ks.set_user_limit(0.01)

        # New base is 1000, regime should be 0.5x = 500
        assert ks.limit == 1000.0 * 0.5


class TestChoppyRegimeHaltsEngine:
    """
    Critical test case from requirements:
    Simulate MTM loss of 3000 with limit of 5000.
    Trigger CHOPPY regime (0.5x multiplier).
    Verify engine halts because new limit is 2500 < 3000.
    """

    def test_choppy_regime_triggers_kill_switch(self):
        """
        MTM loss = 3000, user limit = 5000 (5% of 100k).
        After CHOPPY (0.5x), effective limit = 2500.
        check(3000) should trigger kill switch since 3000 >= 2500.
        """
        trigger_callback = MagicMock()
        ks = HybridKillSwitch(
            starting_capital=100_000,
            user_limit_percent=0.05,  # 5% = 5000
            on_trigger=trigger_callback,
        )

        # With ceiling at 3% (3000), effective limit = min(3000, 5000) = 3000
        # But if ceiling is 3%, let's adjust: use user_limit that's below ceiling
        # For this test, we need limit of 5000.
        # Ceiling is MTM_LOSS_CEILING * 100_000.
        # If ceiling is 3% (default), then ceiling = 3000, so effective = min(3000, 5000) = 3000
        # We need the effective limit to be 5000, so let's increase capital.
        # Capital = 5000 / MTM_LOSS_CEILING = 166667 (if ceiling is 3%)
        # Or we can just use a capital where 5% > ceiling and work with what we get.

        # Let's be explicit: use capital where the math works cleanly.
        # We want user_limit = 5000. With 0.5x regime, limit = 2500. Loss = 3000 -> halt.
        capital = 250_000  # ceiling at 3% = 7500
        ks2 = HybridKillSwitch(
            starting_capital=capital,
            user_limit_percent=0.02,  # 2% of 250k = 5000
            on_trigger=trigger_callback,
        )

        # Verify base limit is 5000
        assert ks2.base_limit == 5000.0

        # MTM loss of 3000 should be OK before regime change
        can_continue = ks2.check(3000.0)
        assert can_continue is True
        assert not ks2.is_triggered

        # Apply CHOPPY regime (0.5x multiplier)
        ks2.apply_regime_multiplier(0.5, "CHOPPY")

        # Effective limit is now 5000 * 0.5 = 2500
        assert ks2.limit == 2500.0

        # MTM loss of 3000 now exceeds limit of 2500 -> should trigger
        can_continue = ks2.check(3000.0)
        assert can_continue is False
        assert ks2.is_triggered

        # Verify callback was invoked
        trigger_callback.assert_called_once()
        call_reason = trigger_callback.call_args[0][0]
        assert "3,000" in call_reason or "3000" in call_reason

    def test_mtm_at_exactly_limit_triggers(self):
        """MTM loss exactly at the limit should trigger the kill switch."""
        ks = HybridKillSwitch(starting_capital=250_000, user_limit_percent=0.02)

        # Limit = 5000
        assert ks.base_limit == 5000.0

        # Loss exactly at limit
        can_continue = ks.check(5000.0)
        assert can_continue is False
        assert ks.is_triggered

    def test_mtm_just_below_limit_continues(self):
        """MTM loss just below the limit should allow continued trading."""
        ks = HybridKillSwitch(starting_capital=250_000, user_limit_percent=0.02)

        can_continue = ks.check(4999.99)
        assert can_continue is True
        assert not ks.is_triggered


class TestKillSwitchBehavior:
    """Test kill switch trigger and reset behavior."""

    def test_trigger_disables_for_day(self):
        """Once triggered, trading should be disabled for the rest of the day."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.02)

        ks.check(5000.0)  # Trigger it
        assert ks.is_triggered
        assert ks.is_disabled_for_day

    def test_check_after_trigger_returns_false(self):
        """After trigger, all check() calls should return False."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.02)

        ks.check(5000.0)  # Trigger
        assert ks.check(0.0) is False  # Even with 0 loss

    def test_reset_requires_confirmation(self):
        """Reset should require explicit confirmation string."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.02)
        ks.manual_trigger("test")

        assert ks.reset("wrong") is False
        assert ks.is_triggered

        assert ks.reset("CONFIRM_RESET") is True
        assert not ks.is_triggered

    def test_manual_trigger(self):
        """manual_trigger should activate the kill switch."""
        callback = MagicMock()
        ks = HybridKillSwitch(
            starting_capital=100_000,
            user_limit_percent=0.02,
            on_trigger=callback,
        )

        ks.manual_trigger("Test trigger")
        assert ks.is_triggered
        callback.assert_called_once()

    def test_get_status(self):
        """get_status should return comprehensive state."""
        ks = HybridKillSwitch(starting_capital=100_000, user_limit_percent=0.02)
        status = ks.get_status()

        assert 'triggered' in status
        assert 'ceiling_percent' in status
        assert 'effective_limit' in status
        assert status['triggered'] is False


class TestLegacyKillSwitch:
    """Test backward compatibility of KillSwitch alias."""

    def test_legacy_killswitch_inherits_hybrid(self):
        """KillSwitch should be a subclass of HybridKillSwitch."""
        assert issubclass(KillSwitch, HybridKillSwitch)

    def test_legacy_killswitch_works(self):
        """KillSwitch with absolute limit should work."""
        ks = KillSwitch(mtm_loss_limit=5000.0)

        # Should have effective limit of min(ceiling, user_limit)
        # For 100k capital, ceiling = 3% = 3000, user = 5% = 5000
        # So effective = 3000 (clamped by ceiling)
        assert ks.base_limit <= ks.ceiling


class TestRateLimiter:
    """Test SEBI rate limiting compliance."""

    def test_initial_state_allows_orders(self):
        """Fresh rate limiter should allow orders."""
        rl = RateLimiter(max_orders_per_second=10)
        assert rl.can_place_order() is True

    def test_rate_limit_enforced(self):
        """After max orders, should block new ones."""
        rl = RateLimiter(max_orders_per_second=3)

        for _ in range(3):
            rl.record_order()

        assert rl.can_place_order() is False

    def test_get_current_rate(self):
        """get_current_rate should reflect recent orders."""
        rl = RateLimiter(max_orders_per_second=10)

        rl.record_order()
        rl.record_order()

        assert rl.get_current_rate() == 2


class TestRiskManager:
    """Test unified risk manager."""

    def test_pre_order_check_with_high_loss(self):
        """Pre-order check should fail with high MTM loss."""
        rm = RiskManager(mtm_loss_limit=5000.0)

        # With a very high loss, should fail
        result = rm.pre_order_check(mtm_loss=10000.0)
        assert result is False

    def test_get_state(self):
        """get_state should return valid RiskState."""
        rm = RiskManager(mtm_loss_limit=5000.0)
        state = rm.get_state(mtm_loss=1000.0)

        assert isinstance(state, RiskState)
        assert state.is_active is True
        assert state.current_mtm_loss == 1000.0

    def test_emergency_stop(self):
        """Emergency stop should trigger kill switch."""
        rm = RiskManager(mtm_loss_limit=5000.0)
        rm.emergency_stop("Test emergency")

        assert rm.kill_switch.is_triggered
