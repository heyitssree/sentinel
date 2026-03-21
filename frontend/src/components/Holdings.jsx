import React, { useState, useEffect, useCallback } from 'react';
import {
  Wallet, RefreshCw, TrendingUp, TrendingDown, Minus,
  AlertTriangle, ToggleLeft, ToggleRight, Loader2, Info
} from 'lucide-react';

const API_BASE = '/api';

function PnlBadge({ value, pct }) {
  const pos = value >= 0;
  return (
    <div className={`text-right ${pos ? 'text-green-400' : 'text-red-400'}`}>
      <p className="font-semibold text-sm">
        {pos ? '+' : ''}₹{Math.abs(value).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
      </p>
      <p className="text-xs opacity-80">
        {pos ? '+' : ''}{pct.toFixed(2)}%
      </p>
    </div>
  );
}

function DayChangeBadge({ change, pct }) {
  if (change === 0 && pct === 0) return null;
  const pos = change >= 0;
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded ${pos ? 'bg-green-500/15 text-green-400' : 'bg-red-500/15 text-red-400'}`}>
      {pos ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
      {pos ? '+' : ''}{pct.toFixed(2)}% today
    </span>
  );
}

function TradingToggle({ ticker, allowed, onChange, loading }) {
  return (
    <button
      onClick={() => onChange(ticker, !allowed)}
      disabled={loading}
      title={allowed ? 'Click to disable automated trading for this stock' : 'Click to enable automated trading for this stock'}
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition border
        ${allowed
          ? 'bg-blue-500/15 text-blue-300 border-blue-500/30 hover:bg-blue-500/25'
          : 'bg-gray-700 text-gray-500 border-gray-600 hover:bg-gray-600'
        } ${loading ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      {loading
        ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
        : allowed
          ? <ToggleRight className="w-3.5 h-3.5" />
          : <ToggleLeft className="w-3.5 h-3.5" />
      }
      {allowed ? 'Auto-trade ON' : 'Auto-trade OFF'}
    </button>
  );
}

function HoldingRow({ holding, onToggle, toggling }) {
  const pnlPos = holding.pnl >= 0;

  return (
    <div className={`bg-gray-800 border rounded-xl p-4 flex flex-col gap-3 transition
      ${pnlPos ? 'border-green-500/20' : 'border-red-500/20'}`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-bold text-white text-base">{holding.ticker}</span>
            <span className="text-xs text-gray-500 bg-gray-700 px-2 py-0.5 rounded">{holding.exchange}</span>
            <span className="text-xs text-gray-500 bg-gray-700 px-2 py-0.5 rounded">{holding.product}</span>
            <DayChangeBadge change={holding.day_change} pct={holding.day_change_percentage} />
          </div>
          <p className="text-xs text-gray-500 mt-0.5">{holding.quantity} shares · avg ₹{holding.avg_price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</p>
        </div>
        <PnlBadge value={holding.pnl} pct={holding.pnl_percent} />
      </div>

      {/* Price row */}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="bg-gray-700/50 rounded-lg px-3 py-2">
          <p className="text-gray-400">Invested</p>
          <p className="text-white font-medium mt-0.5">₹{holding.invested_value.toLocaleString('en-IN', { minimumFractionDigits: 0 })}</p>
        </div>
        <div className="bg-gray-700/50 rounded-lg px-3 py-2">
          <p className="text-gray-400">Current</p>
          <p className="text-white font-medium mt-0.5">₹{holding.current_value.toLocaleString('en-IN', { minimumFractionDigits: 0 })}</p>
        </div>
        <div className="bg-gray-700/50 rounded-lg px-3 py-2">
          <p className="text-gray-400">LTP</p>
          <p className="text-white font-medium mt-0.5">₹{holding.current_price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</p>
        </div>
      </div>

      {/* Toggle */}
      <div className="flex items-center justify-between">
        <TradingToggle
          ticker={holding.ticker}
          allowed={holding.trading_allowed}
          onChange={onToggle}
          loading={toggling === holding.ticker}
        />
        {!holding.trading_allowed && (
          <span className="text-xs text-gray-500 flex items-center gap-1">
            <Info className="w-3 h-3" /> Engine will skip this stock
          </span>
        )}
      </div>
    </div>
  );
}

export default function Holdings({ tradingMode }) {
  const [holdings, setHoldings] = useState([]);
  const [source, setSource] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [toggling, setToggling] = useState(null); // ticker being toggled

  const fetchHoldings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/holdings`);
      if (!res.ok) throw new Error(`Server error: ${res.status}`);
      const data = await res.json();
      setHoldings(data.holdings || []);
      setSource(data.source);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchHoldings(); }, [fetchHoldings]);

  const handleToggle = async (ticker, allowed) => {
    setToggling(ticker);
    try {
      const res = await fetch(`${API_BASE}/holdings/${ticker}/trading-permission`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ allowed }),
      });
      if (!res.ok) throw new Error(`Server error: ${res.status}`);
      setHoldings(prev =>
        prev.map(h => h.ticker === ticker ? { ...h, trading_allowed: allowed } : h)
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setToggling(null);
    }
  };

  const totalInvested = holdings.reduce((s, h) => s + h.invested_value, 0);
  const totalCurrent = holdings.reduce((s, h) => s + h.current_value, 0);
  const totalPnl = totalCurrent - totalInvested;
  const totalPnlPct = totalInvested > 0 ? (totalPnl / totalInvested) * 100 : 0;
  const enabledCount = holdings.filter(h => h.trading_allowed).length;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold flex items-center gap-2">
            <Wallet className="w-5 h-5 text-blue-400" />
            Holdings
            {source && (
              <span className={`text-xs px-2 py-0.5 rounded font-normal
                ${source === 'zerodha' ? 'bg-orange-500/20 text-orange-300' : 'bg-gray-700 text-gray-400'}`}>
                {source === 'zerodha' ? 'Zerodha Demat' : 'Paper Portfolio'}
              </span>
            )}
          </h2>
          <p className="text-sm text-gray-400 mt-0.5">
            {holdings.length} holding{holdings.length !== 1 ? 's' : ''} · {enabledCount} auto-trade enabled
          </p>
        </div>
        <button
          onClick={fetchHoldings}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Summary bar */}
      {holdings.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-gray-800 border border-gray-700 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Invested</p>
            <p className="text-white font-semibold mt-0.5">₹{totalInvested.toLocaleString('en-IN', { minimumFractionDigits: 0 })}</p>
          </div>
          <div className="bg-gray-800 border border-gray-700 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Current Value</p>
            <p className="text-white font-semibold mt-0.5">₹{totalCurrent.toLocaleString('en-IN', { minimumFractionDigits: 0 })}</p>
          </div>
          <div className={`bg-gray-800 border rounded-xl p-3 text-center ${totalPnl >= 0 ? 'border-green-500/30' : 'border-red-500/30'}`}>
            <p className="text-xs text-gray-400">Total P&L</p>
            <p className={`font-semibold mt-0.5 ${totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {totalPnl >= 0 ? '+' : ''}₹{Math.abs(totalPnl).toLocaleString('en-IN', { minimumFractionDigits: 0 })}
              <span className="text-xs ml-1 opacity-80">({totalPnlPct >= 0 ? '+' : ''}{totalPnlPct.toFixed(2)}%)</span>
            </p>
          </div>
        </div>
      )}

      {/* Note about toggle */}
      <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg px-3 py-2 text-xs text-blue-300 flex items-start gap-2">
        <Info className="w-3.5 h-3.5 shrink-0 mt-0.5" />
        <span>The <strong>Auto-trade</strong> toggle controls whether Sentinel's engine may open new positions for that stock. Existing open positions are not affected.</span>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-sm text-red-400 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" />
          {error}
          <button onClick={fetchHoldings} className="underline ml-2">Retry</button>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && holdings.length === 0 && (
        <div className="text-center py-16 text-gray-500">
          <Wallet className="w-12 h-12 mx-auto mb-4 opacity-30" />
          <p className="font-medium">No holdings found</p>
          {source === 'paper'
            ? <p className="text-sm mt-1">Paper trades will appear here once positions are opened.</p>
            : <p className="text-sm mt-1">Connect Zerodha and authenticate daily to see your demat holdings.</p>
          }
        </div>
      )}

      {/* Cards grid */}
      {holdings.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {holdings.map(h => (
            <HoldingRow
              key={h.ticker}
              holding={h}
              onToggle={handleToggle}
              toggling={toggling}
            />
          ))}
        </div>
      )}
    </div>
  );
}
