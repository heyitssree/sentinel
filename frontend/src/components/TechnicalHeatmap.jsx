import React, { useState, useEffect, memo } from 'react';

// Helper functions for RSI colors - defined outside component
const getRSIColor = (rsiStatus) => {
  switch (rsiStatus) {
    case 'bullish': return 'bg-green-500';
    case 'bearish': return 'bg-red-500';
    default: return 'bg-slate-600';
  }
};

const getRSIBorderColor = (rsiStatus) => {
  switch (rsiStatus) {
    case 'bullish': return 'border-green-400';
    case 'bearish': return 'border-red-400';
    default: return 'border-slate-500';
  }
};

// Extracted StockCell component - memoized to prevent unnecessary re-renders
const StockCell = memo(({ stock, activeTicker, onSelectTicker }) => {
  const isActive = stock.ticker === activeTicker;
  const isWatchlist = stock.in_watchlist;

  return (
    <div
      onClick={() => onSelectTicker?.(stock.ticker)}
      className={`
        relative p-2 rounded-lg cursor-pointer transition-all duration-200
        ${getRSIColor(stock.rsi_status)} ${getRSIBorderColor(stock.rsi_status)}
        ${isActive ? 'ring-2 ring-white scale-105' : ''}
        ${isWatchlist ? 'border-2' : 'border border-opacity-30'}
        ${stock.volume_spike ? 'animate-pulse' : ''}
        hover:scale-105 hover:z-10
      `}
      title={`${stock.name}\nRSI: ${stock.rsi?.toFixed(1) || 'N/A'}\nPrice: ₹${stock.price?.toFixed(2) || 'N/A'}`}
    >
      {/* Volume spike glow effect */}
      {stock.volume_spike && (
        <div className="absolute inset-0 rounded-lg bg-yellow-400 opacity-30 animate-ping" />
      )}
      
      <div className="relative z-10">
        <div className="text-xs font-bold text-white truncate">
          {stock.ticker}
        </div>
        <div className="text-xs text-white/80">
          {stock.rsi?.toFixed(0) || '—'}
        </div>
        
        {/* Watchlist indicator */}
        {isWatchlist && (
          <div className="absolute -top-1 -right-1 w-2 h-2 bg-yellow-400 rounded-full" />
        )}
        
        {/* Volume spike indicator */}
        {stock.volume_spike && (
          <div className="absolute -bottom-1 -right-1 text-yellow-400 text-xs">⚡</div>
        )}
      </div>
    </div>
  );
});

StockCell.displayName = 'StockCell';

// Extracted SectorGroup component - memoized to prevent unnecessary re-renders
const SectorGroup = memo(({ sector, activeTicker, onSelectTicker }) => {
  const bullishCount = sector.stocks.filter(s => s.rsi_status === 'bullish').length;
  const bearishCount = sector.stocks.filter(s => s.rsi_status === 'bearish').length;
  const spikeCount = sector.stocks.filter(s => s.volume_spike).length;

  return (
    <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
      <div className="flex justify-between items-center mb-2">
        <h4 className="text-sm font-semibold text-white">{sector.name}</h4>
        <div className="flex gap-2 text-xs">
          <span className="text-green-400">↑{bullishCount}</span>
          <span className="text-red-400">↓{bearishCount}</span>
          {spikeCount > 0 && <span className="text-yellow-400">⚡{spikeCount}</span>}
        </div>
      </div>
      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-1">
        {sector.stocks.map(stock => (
          <StockCell 
            key={stock.ticker} 
            stock={stock} 
            activeTicker={activeTicker}
            onSelectTicker={onSelectTicker}
          />
        ))}
      </div>
    </div>
  );
});

SectorGroup.displayName = 'SectorGroup';

const TechnicalHeatmap = ({ onSelectTicker, activeTicker }) => {
  const [heatmapData, setHeatmapData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState('sectors'); // 'sectors' or 'grid'
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchHeatmap();
    const interval = setInterval(fetchHeatmap, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  const fetchHeatmap = async () => {
    try {
      const response = await fetch('/api/heatmap/nifty50');
      if (!response.ok) throw new Error('Failed to fetch heatmap');
      const data = await response.json();
      setHeatmapData(data);
      setError(null);
    } catch (err) {
      setError(err.message);
      console.error('Heatmap fetch error:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
        <div className="flex items-center justify-center h-48">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
        <div className="text-red-400 text-center py-8">
          Error loading heatmap: {error}
          <button 
            onClick={fetchHeatmap}
            className="block mx-auto mt-2 px-4 py-1 bg-slate-700 rounded text-sm"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
      {/* Header */}
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold text-white flex items-center gap-2">
          <span className="text-2xl">🌡️</span>
          Nifty 50 Heatmap
          <span className="text-xs text-slate-400 font-normal">
            ({heatmapData?.total_stocks || 0} stocks)
          </span>
        </h3>
        
        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="flex bg-slate-700 rounded-lg p-1">
            <button
              onClick={() => setViewMode('sectors')}
              className={`px-2 py-1 text-xs rounded ${
                viewMode === 'sectors' ? 'bg-blue-600 text-white' : 'text-slate-400'
              }`}
            >
              Sectors
            </button>
            <button
              onClick={() => setViewMode('grid')}
              className={`px-2 py-1 text-xs rounded ${
                viewMode === 'grid' ? 'bg-blue-600 text-white' : 'text-slate-400'
              }`}
            >
              Grid
            </button>
          </div>
          
          {/* Refresh button */}
          <button
            onClick={fetchHeatmap}
            className="p-2 bg-slate-700 rounded-lg hover:bg-slate-600 transition-colors"
            title="Refresh"
          >
            🔄
          </button>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mb-4 text-xs text-slate-400">
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 bg-green-500 rounded" />
          <span>RSI &gt; 60</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 bg-red-500 rounded" />
          <span>RSI &lt; 40</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 bg-slate-600 rounded" />
          <span>Neutral</span>
        </div>
        <div className="flex items-center gap-1">
          <span>⚡</span>
          <span>Volume Spike</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 bg-yellow-400 rounded-full" />
          <span>Watchlist</span>
        </div>
      </div>

      {/* Heatmap Content */}
      <div className="max-h-[500px] overflow-y-auto">
        {viewMode === 'sectors' ? (
          <div className="space-y-3">
            {heatmapData?.sectors?.map(sector => (
              <SectorGroup 
                key={sector.name} 
                sector={sector} 
                activeTicker={activeTicker}
                onSelectTicker={onSelectTicker}
              />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-5 sm:grid-cols-8 md:grid-cols-10 gap-1">
            {heatmapData?.stocks?.map(stock => (
              <StockCell 
                key={stock.ticker} 
                stock={stock} 
                activeTicker={activeTicker}
                onSelectTicker={onSelectTicker}
              />
            ))}
          </div>
        )}
      </div>

      {/* Summary Stats */}
      <div className="mt-4 pt-3 border-t border-slate-700 grid grid-cols-4 gap-2 text-center text-xs">
        <div>
          <div className="text-green-400 font-bold">
            {heatmapData?.stocks?.filter(s => s.rsi_status === 'bullish').length || 0}
          </div>
          <div className="text-slate-500">Bullish</div>
        </div>
        <div>
          <div className="text-red-400 font-bold">
            {heatmapData?.stocks?.filter(s => s.rsi_status === 'bearish').length || 0}
          </div>
          <div className="text-slate-500">Bearish</div>
        </div>
        <div>
          <div className="text-slate-400 font-bold">
            {heatmapData?.stocks?.filter(s => s.rsi_status === 'neutral').length || 0}
          </div>
          <div className="text-slate-500">Neutral</div>
        </div>
        <div>
          <div className="text-yellow-400 font-bold">
            {heatmapData?.stocks?.filter(s => s.volume_spike).length || 0}
          </div>
          <div className="text-slate-500">Vol Spikes</div>
        </div>
      </div>

      {/* Last updated */}
      <div className="mt-2 text-xs text-slate-500 text-right">
        Last updated: {heatmapData?.timestamp ? new Date(heatmapData.timestamp).toLocaleTimeString() : '—'}
      </div>
    </div>
  );
};

export default TechnicalHeatmap;
