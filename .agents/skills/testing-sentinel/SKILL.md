# Testing The Sentinel

## Overview
The Sentinel is a Python-based algorithmic trading engine. Testing uses pytest for unit/integration tests and `--mock --test` mode for end-to-end verification.

## Running Tests

### Unit & Integration Tests
```bash
python -m pytest tests/ -v
```
- Tests are in `tests/` directory with shared fixtures in `tests/conftest.py`
- Key fixture: `temp_db` creates a temporary DuckDB database
- Key fixture: `mock_kite` provides MockKite + MockTicker pair
- Key fixture: `sample_trades` generates 5 sample trades (3 wins, 2 losses)
- No external API keys or credentials needed — all tests use mocks

### Mock Mode (End-to-End)
```bash
python main.py --mock --test
```
- `--mock` bypasses real Zerodha/Gemini API calls
- `--test` runs a single heartbeat cycle then shuts down (takes ~10 seconds)
- Verify output shows: initialization of all components, heartbeat execution, autopsy run, graceful shutdown
- No tracebacks or unhandled exceptions should appear

## Key Test Areas

### Risk Management (`tests/test_risk_management.py`)
- HybridKillSwitch: hard-coded ceiling cannot be overridden by user limit
- Regime multiplier: CHOPPY market (0.5x) reduces effective loss limit
- Critical scenario: ₹3k MTM loss with ₹5k limit + CHOPPY 0.5x → limit becomes ₹2.5k → engine halts

### Concurrency (`tests/test_concurrency.py`)
- `_candle_lock` thread safety under high-frequency tick bursts
- `ThreadPoolExecutor` timeout handling with `as_completed()`
- The `TimeoutError` from `as_completed()` must be caught (was a bug previously)

### AI Models (`tests/test_ai_models.py`)
- Pydantic model validation for edge cases (empty data, boundary values)
- HOLD recommendations with low confidence must NOT trigger trades
- BUY with confidence < 0.6 or "high risk" factor must be blocked

### Autopsy Pipeline (`tests/test_autopsy_pipeline.py`)
- MockPostTradeAutopsy with 5-trade simulation
- Report generation, formatting, and file saving to `/reports`
- Opportunity cost analysis format

## Common Issues

- `SentinelDB.insert_candle()` expects `open_` (not `open`) as parameter name — Python reserved word avoidance
- f-string ternary expressions must be extracted to variables before use in format specifiers (e.g., `:.2f`)
- `MockPostTradeAutopsy.analyze` signature must match `PostTradeAutopsy.analyze` including optional params
- Market hours are IST (9:15 AM - 3:30 PM), so mock test mode outside these hours triggers "market closing" path

## Devin Secrets Needed
None — all testing uses mock mode and does not require API keys.
