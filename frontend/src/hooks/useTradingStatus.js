import { useState, useCallback } from 'react';

const API_BASE = '/api';

/**
 * Fetches and stores core trading state: engine status, positions,
 * trades, and watchlist.  Call fetchData() to refresh manually, or
 * wire it to a polling interval in the consuming component.
 */
export function useTradingStatus() {
  const [status, setStatus] = useState(null);
  const [positions, setPositions] = useState([]);
  const [trades, setTrades] = useState([]);
  const [availableStocks, setAvailableStocks] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, positionsRes, tradesRes, watchlistRes] = await Promise.all([
        fetch(`${API_BASE}/status`),
        fetch(`${API_BASE}/positions`),
        fetch(`${API_BASE}/trades?limit=20`),
        fetch(`${API_BASE}/watchlist`),
      ]);
      setStatus(await statusRes.json());
      setPositions((await positionsRes.json()).positions);
      setTrades((await tradesRes.json()).trades);
      const wlData = await watchlistRes.json();
      setAvailableStocks(wlData.available || []);
    } catch {
      // network error — keep stale data, let polling retry
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchTradingPhase = useCallback(async (setTradingPhase) => {
    try {
      const res = await fetch(`${API_BASE}/schedule/phase`);
      setTradingPhase(await res.json());
    } catch {
      // ignore
    }
  }, []);

  return { status, setStatus, positions, trades, availableStocks, loading, fetchData, fetchTradingPhase };
}
