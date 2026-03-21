# Sentinel Codebase Audit - Issues & Remediation Plan

**Audit Date:** 2026-03-10 (Updated)  
**Auditor:** Senior Software Architect & Security Engineer  
**Scope:** Full codebase security, stability, performance, and AI-specific issues

---

## Executive Summary

The Sentinel is a paper trading engine integrating Zerodha Kite API with Gemini AI for sentiment and visual analysis. The codebase is well-structured but contains several issues requiring attention across security, stability, and performance domains.

**Critical Issues:** 3 (NEW: +1)  
**High Priority:** 7 (NEW: +1)  
**Medium Priority:** 9 (NEW: +1)  
**Low Priority:** 4

---

## 🔴 NEW CRITICAL: Exposed API Keys in .env

### C0. Real API Keys Committed/Exposed
**File:** `.env`  
**Type:** Security - Credential Exposure  
**Description:** The `.env` file contains real API keys for Zerodha Kite and Google Gemini:
```
KITE_API_KEY=ghd03fvwdy20i1mo
KITE_API_SECRET=4v5c6j0uy9j3ucfhvgwif6va9qoqdgqo
GEMINI_API_KEY='AIzaSyBWokdatlf0xzx4aozU2plWXBm-YPsqugU'
```
**Risk:** These credentials can be used to execute trades, access account data, or incur API costs.  
**Fix:** 
1. Rotate ALL exposed keys immediately
2. Ensure `.env` is in `.gitignore` (verified: it is)
3. Check git history for committed secrets
4. Use placeholder values in `.env.example`  

---

## 🔴 CRITICAL Issues

### C1. SSL Verification Disabled Globally in News Scraper
**File:** `src/ingestion/news_scraper.py:23-28`  
**Type:** Security Vulnerability  
**Description:** SSL verification is disabled globally at module import, affecting ALL HTTPS connections system-wide, not just the news scraper.
```python
ssl._create_default_https_context = ssl._create_unverified_context
```
**Risk:** Man-in-the-middle attacks on any HTTPS connection including API calls to Gemini and Zerodha.  
**Fix:** Use a session-specific context or certifi certificates instead of disabling SSL globally.

### C2. Division by Zero in Autopsy Report Formatting
**File:** `src/gemini/autopsy.py:290`  
**Type:** Logic Bug (Crash)  
**Description:** Division by `result.total_trades` without zero-check.
```python
f"Winning Trades:  {result.winning_trades} ({result.winning_trades/result.total_trades*100:.1f}% win rate)"
```
**Risk:** ZeroDivisionError crash when no trades exist but format_report is called.  
**Fix:** Add guard: `(result.winning_trades/result.total_trades*100 if result.total_trades > 0 else 0:.1f)`

---

## 🟠 HIGH Priority Issues

### H1. Blocking `time.sleep()` in Async Context
**Files:** `src/gemini/sentiment.py`, `src/gemini/vision.py`, `src/gemini/autopsy.py`  
**Type:** Performance/Blocking I/O  
**Description:** Rate limiting and retry logic use `time.sleep()` which blocks the event loop when called from async endpoints in FastAPI.  
**Risk:** Server becomes unresponsive during Gemini API calls.  
**Fix:** Use `asyncio.sleep()` in async methods; ensure sync methods aren't called from async context.

### H2. Unprotected Attribute Access on `VisualAuditResponse`
**File:** `src/gemini/vision.py:198-203`  
**Type:** Potential AttributeError  
**Description:** Accessing `.value` on enum fields assumes Pydantic model parsed correctly.
```python
safety=result.safety.value,
rsi_assessment=result.rsi_assessment.value
```
**Risk:** AttributeError if Gemini returns unexpected format despite schema.  
**Fix:** Add defensive checks or try/except wrapper.

### H3. Stale Model Reference in Multi-Timeframe Analysis
**File:** `src/gemini/vision.py:265`  
**Type:** Bug - Undefined Variable  
**Description:** `self.model` is used but class uses `self.client` (new SDK pattern).
```python
response = self.model.generate_content(content)  # self.model doesn't exist!
```
**Risk:** AttributeError crash when `analyze_multi_timeframe` is called.  
**Fix:** Update to use `self.client.models.generate_content()`.

### H4. Race Condition in News Cache
**File:** `src/ingestion/news_scraper.py:249-251`  
**Type:** Race Condition  
**Description:** Global news cache is updated without lock protection while per-ticker cache uses `_cache_lock`.
```python
if all_items:
    self._all_news_cache = all_items  # No lock!
    self._all_news_cache_time = datetime.now()
```
**Risk:** Inconsistent cache state under concurrent requests.  
**Fix:** Protect with `self._cache_lock`.

### H5. Missing Error Handling in WebSocket Broadcast
**File:** `src/api/server.py:127-129`  
**Type:** Silent Failure  
**Description:** Empty except block swallows all errors during broadcast.
```python
except:
    pass
```
**Risk:** Connection issues go undetected; dead connections accumulate.  
**Fix:** Log errors, remove dead connections, use specific exception types.

### H6. Executor `close_trade` Method Doesn't Exist
**File:** `src/api/server.py:1250`  
**Type:** Bug - Method Name Mismatch  
**Description:** Calls `engine.executor.close_trade(ticker, ...)` but executor has `exit_by_ticker()`.
```python
closed = engine.executor.close_trade(ticker, reason="Manual close from dashboard")
```
**Risk:** AttributeError on manual position close from dashboard.  
**Fix:** Use `engine.executor.exit_by_ticker(ticker, reason=...)`.

---

## 🟡 MEDIUM Priority Issues

### M1. Undefined `ENV_FILE` Variable Before Use
**File:** `src/api/server.py:1195`  
**Type:** Bug - Variable Order  
**Description:** `ENV_FILE` is used at line 1195 but defined at line 1306.  
**Fix:** Move `ENV_FILE` definition to top of file or before first use.

### M2. Inconsistent Null Handling in `get_volume_spike_info`
**File:** `src/signals/indicators.py:274-298`  
**Type:** Edge Case Handling  
**Description:** Returns `volume=0` and `volume_sma=0` when insufficient data, but callers may not expect this.  
**Fix:** Return explicit `None` values or raise for insufficient data.

### M3. Potential Memory Leak in Thread Pool
**File:** `main.py:477`  
**Type:** Resource Management  
**Description:** `cancel_futures=True` in Python 3.9+ may leave some futures in incomplete state.  
**Fix:** Add explicit cleanup and verify thread termination.

### M4. Hardcoded CORS Allow All Origins
**File:** `src/api/server.py:503-509`  
**Type:** Security - Overly Permissive  
**Description:** `allow_origins=["*"]` permits any website to make API calls.  
**Risk:** CSRF attacks, unauthorized API access in production.  
**Fix:** Configure specific allowed origins from environment variable.

### M5. No Input Validation on Ticker Symbols
**File:** `src/api/server.py:693-731` (news endpoint)  
**Type:** Input Validation  
**Description:** Ticker symbols are uppercased but not validated against allowed characters.  
**Risk:** Potential injection if ticker is used in file paths or queries.  
**Fix:** Validate ticker matches `^[A-Z]+$` pattern.

### M6. Singleton Database Instance Not Thread-Safe
**File:** `src/storage/db.py:816-821`  
**Type:** Thread Safety  
**Description:** Global `_db_instance` check and assignment isn't atomic.  
**Fix:** Use threading.Lock for singleton initialization.

### M7. Missing Timeout on `as_completed` Futures
**File:** `main.py:381`  
**Type:** Potential Hang  
**Description:** While timeout is set, individual `future.result(timeout=10)` can still block.  
**Fix:** Ensure total timeout is enforced; cancel remaining futures on timeout.

### M8. News Scraper Clears All Seen Headlines on Force Refresh
**File:** `src/ingestion/news_scraper.py:279-280`  
**Type:** Logic Issue  
**Description:** Force refresh clears ALL seen headlines, causing duplicate processing.  
**Fix:** Only clear headlines older than cache TTL.

---

## 🟢 LOW Priority Issues

### L1. Deprecated `np.bool_` Type Check
**File:** `src/api/server.py:93`  
**Type:** Deprecation Warning  
**Description:** `np.bool_` is deprecated in NumPy 2.0.  
**Fix:** Use `np.bool_` only, remove `np.bool8`.

### L2. Inconsistent Logging Format
**Files:** Multiple  
**Type:** Code Quality  
**Description:** Some files use f-strings with logger, others use % formatting.  
**Fix:** Standardize on lazy % formatting for performance.

### L3. Magic Numbers in Trading Logic
**File:** `src/api/server.py:448-453`  
**Type:** Maintainability  
**Description:** Hardcoded 2% profit and 1% loss thresholds.  
**Fix:** Move to configuration constants.

### L4. Missing Type Hints in Several Functions
**Files:** Various  
**Type:** Code Quality  
**Description:** Some functions lack return type hints.  
**Fix:** Add comprehensive type hints for better IDE support and documentation.

---

## AI-Specific Issues

### A1. Happy Path Only in Gemini Response Parsing
**Files:** `src/gemini/vision.py`, `src/gemini/sentiment.py`  
**Type:** AI Edge Case  
**Description:** Pydantic parsing assumes Gemini always returns valid JSON matching schema.  
**Risk:** Crash on malformed AI responses, hallucinated fields, or API changes.  
**Fix:** Wrap parsing in try/except, return safe defaults on failure.

### A2. No Confidence Threshold Enforcement
**File:** `src/gemini/vision.py:371`  
**Type:** AI Logic Gap  
**Description:** `is_safe_to_enter` checks safety level but ignores low confidence scores.  
**Risk:** Trading on uncertain AI assessments.  
**Fix:** Add minimum confidence threshold (e.g., 0.6).

### A3. Stale Chart Analysis
**File:** `main.py:306-310`  
**Type:** Data Freshness  
**Description:** Chart is generated then analyzed; price could move significantly during API call.  
**Fix:** Add timestamp validation, reject if chart age > threshold.

---

## NEW: Additional Issues Found (2026-03-10)

### H7. SQL Injection Vector in Database Stats
**File:** `src/storage/db.py:792`  
**Type:** SQL Injection  
**Description:** Table name is interpolated directly into SQL query:
```python
result = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
```
**Risk:** Although `table` comes from a hardcoded list, this pattern is dangerous.  
**Fix:** Validate table name against whitelist or use parameterized identifier.

### M9. Bare Except Clause in News Scraper
**File:** `src/ingestion/news_scraper.py:198`  
**Type:** Error Handling  
**Description:** Bare `except:` clause swallows all exceptions silently:
```python
except:
    pass
```
**Risk:** Hides bugs, makes debugging difficult.  
**Fix:** Use specific exception types or at minimum log the error.

### M10. Server Binds to 0.0.0.0
**File:** `src/api/server.py:1722`  
**Type:** Security - Network Exposure  
**Description:** Server binds to all interfaces by default.  
**Risk:** Exposes API to entire network, not just localhost.  
**Fix:** Default to `127.0.0.1`, allow override via env var for production.

---

## Remediation Priority Order

1. **C0** - Exposed API Keys (IMMEDIATE - Rotate credentials)
2. **C1** - SSL Global Disable (Security Critical)
3. **C2** - Division by Zero (Crash)
4. **H3** - Stale model reference (Crash)
5. **H6** - close_trade method mismatch (Crash)
6. **H7** - SQL Injection pattern (Security)
7. **M1** - ENV_FILE undefined (Crash)
8. **H1** - Blocking sleep in async (Performance)
9. **H4** - Race condition in cache (Data Integrity)
10. **H5** - Silent WebSocket errors (Debugging)
11. **M9** - Bare except clause (Error Handling)
12. **M10** - Server 0.0.0.0 binding (Security)
13. **H2** - Unprotected enum access (Stability)
14. **M4** - CORS wildcard (Security)
15. **M6** - Thread-unsafe singleton (Stability)
16. **A1** - AI response edge cases (Reliability)
17. **A2** - Confidence threshold (Trading Safety)

---

## Files Modified Summary

| File | Issues |
|------|--------|
| `src/ingestion/news_scraper.py` | C1, H4, M8 |
| `src/gemini/autopsy.py` | C2 |
| `src/gemini/vision.py` | H2, H3, A1, A2 |
| `src/api/server.py` | H5, H6, M1, M4, M5, L1 |
| `src/gemini/sentiment.py` | H1, A1 |
| `src/storage/db.py` | M6 |
| `main.py` | M3, M7, A3 |
| `src/signals/indicators.py` | M2 |

---

## Post-Fix Verification

After each fix:
1. Run syntax check: `python -m py_compile <file>`
2. Import test: `python -c "from src.module import Class"`
3. Manual endpoint test where applicable
4. Document in changelog

---

*This audit follows the constraint of not removing functionality - all fixes refactor insecure/buggy patterns into secure versions following existing conventions.*
