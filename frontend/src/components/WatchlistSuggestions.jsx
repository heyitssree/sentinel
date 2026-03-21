import React, { useState, useEffect, useCallback } from 'react';
import {
  Sparkles, RefreshCw, Plus, CheckCircle, Clock,
  TrendingUp, TrendingDown, Minus, AlertTriangle, Brain
} from 'lucide-react';

const API_BASE = '/api';

// Score bar with colour gradient
function ScoreBar({ value }) {
  const pct = Math.round(value * 100);
  const colour =
    pct >= 65 ? 'bg-green-500' :
    pct >= 45 ? 'bg-yellow-500' :
    'bg-red-500';
  return (
    <div className="w-full bg-gray-700 rounded-full h-1.5 mt-1">
      <div className={`${colour} h-1.5 rounded-full transition-all`} style={{ width: `${pct}%` }} />
    </div>
  );
}

// Chip badge
function Chip({ label, value, colour }) {
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${colour}`}>
      {label}: <strong>{value}</strong>
    </span>
  );
}

function RecommendationIcon({ rec }) {
  if (rec === 'BUY')  return <TrendingUp  className="w-4 h-4 text-green-400" />;
  if (rec === 'SELL') return <TrendingDown className="w-4 h-4 text-red-400" />;
  return <Minus className="w-4 h-4 text-yellow-400" />;
}

function SuggestionCard({ stock, watchlist, onAdd }) {
  const inWatchlist = watchlist.includes(stock.ticker);
  const watchlistFull = watchlist.length >= 10;
  const scorePct = Math.round(stock.combined_score * 100);
  const sentimentPct = Math.round(stock.sentiment_score * 100);
  const techPct = Math.round(stock.technical_score * 100);

  return (
    <div className="bg-gray-800 border border-gray-700 hover:border-blue-500/50 rounded-xl p-4 flex flex-col gap-3 transition-colors">
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-white text-lg">{stock.ticker}</span>
            <span className="text-xs text-gray-500 bg-gray-700 px-2 py-0.5 rounded">NSE</span>
            {stock.recommendation && (
              <RecommendationIcon rec={stock.recommendation} />
            )}
          </div>
          {stock.name && stock.name !== stock.ticker && (
            <p className="text-xs text-gray-400 mt-0.5">{stock.name}</p>
          )}
          <p className="text-xs text-gray-500">{stock.sector}</p>
        </div>

        <div className="text-right shrink-0">
          <p className="text-white font-semibold">₹{stock.price?.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</p>
          <p className="text-xs text-gray-400">RSI {stock.rsi}</p>
        </div>
      </div>

      {/* Combined score */}
      <div>
        <div className="flex justify-between text-xs mb-1">
          <span className="text-gray-400">Combined Score</span>
          <span className={`font-bold ${scorePct >= 65 ? 'text-green-400' : scorePct >= 45 ? 'text-yellow-400' : 'text-red-400'}`}>
            {scorePct}/100
          </span>
        </div>
        <ScoreBar value={stock.combined_score} />
      </div>

      {/* Score chips */}
      <div className="flex flex-wrap gap-1.5">
        <Chip label="Tech" value={`${techPct}%`}
          colour={techPct >= 60 ? 'bg-blue-500/20 text-blue-300' : 'bg-gray-700 text-gray-400'} />
        <Chip label="Sentiment" value={`${sentimentPct}%`}
          colour={sentimentPct >= 60 ? 'bg-purple-500/20 text-purple-300' : 'bg-gray-700 text-gray-400'} />
        {stock.pattern && stock.pattern !== 'None' && (
          <Chip label="Pattern" value={stock.pattern}
            colour="bg-cyan-500/20 text-cyan-300" />
        )}
      </div>

      {/* Gemini reasoning */}
      {stock.reasoning && (
        <p className="text-xs text-gray-400 leading-relaxed border-t border-gray-700 pt-2">
          <Brain className="w-3 h-3 inline mr-1 text-purple-400" />
          {stock.reasoning}
        </p>
      )}

      {/* Add button */}
      <button
        onClick={() => onAdd(stock.ticker)}
        disabled={inWatchlist || watchlistFull}
        className={`w-full flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-medium transition
          ${inWatchlist
            ? 'bg-green-500/10 text-green-400 border border-green-500/30 cursor-default'
            : watchlistFull
            ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
            : 'bg-blue-600 hover:bg-blue-500 text-white'
          }`}
      >
        {inWatchlist
          ? <><CheckCircle className="w-4 h-4" /> In Watchlist</>
          : watchlistFull
          ? <><AlertTriangle className="w-4 h-4" /> Watchlist Full (10/10)</>
          : <><Plus className="w-4 h-4" /> Add to Watchlist</>
        }
      </button>
    </div>
  );
}

export default function WatchlistSuggestions({ watchlist, onAdd }) {
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [lastScan, setLastScan] = useState(null);
  const [error, setError] = useState(null);
  const [cached, setCached] = useState(false);

  const fetchSuggestions = useCallback(async (force = false) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/watchlist/suggestions?force=${force}`);
      if (!res.ok) throw new Error(`Server error: ${res.status}`);
      const data = await res.json();
      setSuggestions(data.suggestions || []);
      setLastScan(data.last_scan);
      setCached(data.cached);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Load cached suggestions on mount
  useEffect(() => {
    fetchSuggestions(false);
  }, [fetchSuggestions]);

  const formatScanTime = (iso) => {
    if (!iso) return null;
    const d = new Date(iso);
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
  };

  const buyCount = suggestions.filter(s => s.recommendation === 'BUY').length;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-yellow-400" />
            AI Stock Suggestions
          </h2>
          <p className="text-sm text-gray-400 mt-0.5">
            Gemini ranks Nifty 50 by technical + sentiment score. Approve to watchlist.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {lastScan && (
            <div className="text-right">
              <p className="text-xs text-gray-500 flex items-center gap-1 justify-end">
                <Clock className="w-3 h-3" />
                {cached ? 'Cached' : 'Live scan'} at {formatScanTime(lastScan)}
              </p>
              {buyCount > 0 && (
                <p className="text-xs text-green-400">{buyCount} BUY signal{buyCount > 1 ? 's' : ''}</p>
              )}
            </div>
          )}
          <button
            onClick={() => fetchSuggestions(true)}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-yellow-500/20 text-yellow-300 hover:bg-yellow-500/30 border border-yellow-500/30 rounded-lg text-sm font-medium transition disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            {loading ? 'Scanning…' : 'Scan Now'}
          </button>
        </div>
      </div>

      {/* Status bar */}
      {loading && (
        <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3 text-sm text-yellow-300 flex items-center gap-2">
          <Brain className="w-4 h-4 animate-pulse" />
          Gemini is analyzing Nifty 50 stocks — scoring technical signals, sentiment, and patterns…
          <span className="text-xs text-gray-400">(~2-3 min)</span>
        </div>
      )}

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-sm text-red-400 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" />
          {error}
          <button onClick={() => fetchSuggestions(true)} className="underline ml-2">Retry</button>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && suggestions.length === 0 && (
        <div className="text-center py-16 text-gray-500">
          <Sparkles className="w-12 h-12 mx-auto mb-4 opacity-30" />
          <p className="font-medium">No suggestions yet</p>
          <p className="text-sm mt-1">Click <strong>Scan Now</strong> to analyse Nifty 50 stocks</p>
          <p className="text-xs mt-1 text-gray-600">Auto-scans at market open (9:15 AM)</p>
        </div>
      )}

      {/* Cards grid */}
      {suggestions.length > 0 && (
        <>
          <p className="text-xs text-gray-500">
            Showing top {suggestions.length} stocks · Watchlist {watchlist.length}/10
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {suggestions.map(stock => (
              <SuggestionCard
                key={stock.ticker}
                stock={stock}
                watchlist={watchlist}
                onAdd={onAdd}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
