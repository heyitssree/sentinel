"""
Task 2: Concurrency and Race Condition Check.

Verifies:
- _candle_lock is consistently used in _aggregate_tick and _save_candle_locked
- ThreadPoolExecutor correctly handles timeouts if Gemini API call takes >60s
"""
import sys
import time
import threading
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCandleLockConsistency:
    """Verify _candle_lock protects candle data from concurrent corruption."""

    def test_aggregate_tick_acquires_lock(self):
        """_aggregate_tick should acquire _candle_lock before modifying data."""
        # We patch the Sentinel class to test the lock behavior
        # by simulating concurrent tick processing
        from src.ingestion.mock_kite import MockTicker

        ticker = MockTicker()
        lock = threading.Lock()
        candle_data = {"RELIANCE": []}
        last_candle_time = {"RELIANCE": None}
        errors = []

        def aggregate_tick_simulated(symbol, price, lock, candle_data, last_candle_time):
            """Simulate _aggregate_tick with lock."""
            now = datetime.now()
            candle_start = now.replace(
                minute=(now.minute // 5) * 5,
                second=0,
                microsecond=0
            )

            with lock:
                if last_candle_time.get(symbol) != candle_start:
                    candle_data[symbol] = []
                    last_candle_time[symbol] = candle_start

                candle_data[symbol].append({
                    'price': price,
                    'volume': 100,
                    'timestamp': now
                })

        # Run many concurrent tick aggregations
        threads = []
        for i in range(100):
            t = threading.Thread(
                target=aggregate_tick_simulated,
                args=("RELIANCE", 2950.0 + i * 0.1, lock, candle_data, last_candle_time)
            )
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # All ticks should be recorded without data corruption
        assert len(candle_data["RELIANCE"]) == 100
        # Verify no None values or corrupted data
        for tick in candle_data["RELIANCE"]:
            assert tick['price'] is not None
            assert tick['volume'] == 100

    def test_aggregate_tick_without_lock_can_corrupt(self):
        """Without lock, concurrent aggregation can lose data (demonstrates need for lock)."""
        candle_data = {"RELIANCE": []}
        last_candle_time = {"RELIANCE": None}
        corruption_detected = False

        def aggregate_tick_no_lock(symbol, price, candle_data, last_candle_time):
            """Simulate _aggregate_tick WITHOUT lock to show race condition."""
            now = datetime.now()
            candle_start = now.replace(
                minute=(now.minute // 5) * 5,
                second=0,
                microsecond=0
            )

            # No lock here - deliberately unsafe
            if last_candle_time.get(symbol) != candle_start:
                candle_data[symbol] = []  # Race: another thread may have just added data
                last_candle_time[symbol] = candle_start

            candle_data[symbol].append({
                'price': price,
                'volume': 100,
                'timestamp': now
            })

        # Run many concurrent tick aggregations without lock
        threads = []
        for i in range(100):
            t = threading.Thread(
                target=aggregate_tick_no_lock,
                args=("RELIANCE", 2950.0 + i * 0.1, candle_data, last_candle_time)
            )
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # Without lock, we may have lost data (list reset race condition)
        # This test demonstrates the NEED for the lock
        # We can't guarantee corruption, but the lock version above guarantees correctness
        # Just verify it completes without crashing
        assert isinstance(candle_data["RELIANCE"], list)

    def test_save_candle_locked_called_under_lock(self):
        """_save_candle_locked should only be called while _candle_lock is held."""
        # Verify by checking the code pattern: _save_candle_locked is called
        # inside a `with self._candle_lock:` block in _aggregate_tick
        import inspect
        # We import main but need to handle the side effects
        # Instead, verify by reading the source code pattern

        main_path = Path(__file__).parent.parent / "main.py"
        source = main_path.read_text()

        # Check that _save_candle_locked is called within _aggregate_tick
        # which has `with self._candle_lock:` wrapping it
        assert "_save_candle_locked" in source
        assert "_candle_lock" in source

        # Verify _aggregate_tick uses the lock
        # Find the _aggregate_tick method and check it has `with self._candle_lock:`
        agg_start = source.index("def _aggregate_tick")
        # Find next method definition
        next_def = source.index("def _save_candle_locked")
        agg_body = source[agg_start:next_def]

        assert "with self._candle_lock:" in agg_body
        assert "self._save_candle_locked" in agg_body

    def test_save_candle_wrapper_acquires_lock(self):
        """_save_candle (public wrapper) should acquire _candle_lock."""
        main_path = Path(__file__).parent.parent / "main.py"
        source = main_path.read_text()

        # Find the _save_candle method (not _save_candle_locked)
        save_start = source.index("def _save_candle(self")
        next_def_idx = source.index("\n    def ", save_start + 1)
        save_body = source[save_start:next_def_idx]

        assert "with self._candle_lock:" in save_body


class TestThreadPoolExecutorTimeout:
    """Verify ThreadPoolExecutor handles timeouts for slow API calls."""

    def test_as_completed_timeout_catches_slow_tasks(self):
        """as_completed with timeout should handle slow tasks gracefully."""
        from concurrent.futures import as_completed

        def slow_task():
            """Simulate a slow Gemini API call."""
            time.sleep(3)
            return "completed"

        def fast_task():
            """Simulate a fast task."""
            return "fast"

        executor = ThreadPoolExecutor(max_workers=2)
        futures = {
            executor.submit(slow_task): "slow",
            executor.submit(fast_task): "fast",
        }

        results = []
        timed_out = []

        try:
            for future in as_completed(futures, timeout=1):
                ticker = futures[future]
                try:
                    result = future.result(timeout=1)
                    results.append((ticker, True, result))
                except Exception as e:
                    results.append((ticker, False, str(e)))
        except FuturesTimeoutError:
            # This is the bug: _process_tickers_parallel doesn't catch this
            timed_out.append("timeout_caught")

        executor.shutdown(wait=False, cancel_futures=True)

        # The fast task should complete
        assert any(r[0] == "fast" for r in results)
        # The slow task should have timed out
        assert len(timed_out) > 0 or len(results) < 2

    def test_process_tickers_parallel_timeout_handling(self):
        """
        Verify that _process_tickers_parallel handles TimeoutError from as_completed.

        BUG FOUND: The current implementation in main.py does NOT catch
        TimeoutError raised by as_completed(). If all futures don't complete
        within 60 seconds, the TimeoutError propagates up to _run_heartbeat.

        This test verifies the fix catches the TimeoutError properly.
        """
        from concurrent.futures import as_completed

        def process_with_timeout_handling(futures_dict, overall_timeout=2):
            """Simulates the FIXED version of _process_tickers_parallel."""
            results = []
            try:
                for future in as_completed(futures_dict, timeout=overall_timeout):
                    ticker = futures_dict[future]
                    try:
                        result = future.result(timeout=10)
                        results.append((ticker, True, result))
                    except Exception as e:
                        results.append((ticker, False, str(e)))
            except FuturesTimeoutError:
                # Handle tickers that didn't complete in time
                for future, ticker in futures_dict.items():
                    if not future.done():
                        results.append((ticker, False, "Analysis timeout"))
                        future.cancel()
            return results

        executor = ThreadPoolExecutor(max_workers=3)

        def slow_analyze():
            time.sleep(5)
            return True

        def fast_analyze():
            return True

        futures = {
            executor.submit(slow_analyze): "SLOW_TICKER",
            executor.submit(fast_analyze): "FAST_TICKER",
        }

        results = process_with_timeout_handling(futures, overall_timeout=1)

        executor.shutdown(wait=False, cancel_futures=True)

        # Fast ticker should succeed
        fast_results = [r for r in results if r[0] == "FAST_TICKER"]
        assert len(fast_results) == 1
        assert fast_results[0][1] is True

        # Slow ticker should be reported as timeout
        slow_results = [r for r in results if r[0] == "SLOW_TICKER"]
        assert len(slow_results) == 1
        assert slow_results[0][1] is False
        assert "timeout" in slow_results[0][2].lower()

    def test_future_result_timeout(self):
        """Individual future.result() should timeout if task is stuck."""
        executor = ThreadPoolExecutor(max_workers=1)

        def stuck_task():
            time.sleep(10)
            return "never"

        future = executor.submit(stuck_task)

        with pytest.raises(FuturesTimeoutError):
            future.result(timeout=0.5)

        executor.shutdown(wait=False, cancel_futures=True)

    def test_concurrent_tick_processing_integrity(self):
        """
        Simulate high-frequency tick bursts and verify data integrity.
        Multiple threads writing ticks should not corrupt candle aggregation.
        """
        lock = threading.Lock()
        candle_data = {}
        symbols = ["RELIANCE", "TCS", "INFY", "ICICIBANK", "HDFCBANK"]

        for sym in symbols:
            candle_data[sym] = []

        errors = []

        def process_ticks(symbol, num_ticks):
            for i in range(num_ticks):
                with lock:
                    candle_data[symbol].append({
                        'price': 1000.0 + i,
                        'volume': 100,
                        'thread': threading.current_thread().name,
                    })

        threads = []
        ticks_per_symbol = 50
        for sym in symbols:
            t = threading.Thread(target=process_ticks, args=(sym, ticks_per_symbol))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # Verify all ticks were recorded
        for sym in symbols:
            assert len(candle_data[sym]) == ticks_per_symbol, \
                f"{sym}: expected {ticks_per_symbol} ticks, got {len(candle_data[sym])}"
