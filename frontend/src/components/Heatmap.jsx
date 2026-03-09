import React, { useState, useEffect } from 'react';

const Heatmap = ({ stocks = [], onSelectTicker, selectedTicker, websocket }) => {
  const [stockData, setStockData] = useState({});

  useEffect(() => {
    if (!websocket) return;

    const handleMessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        if (data.type === 'heatmap_update' || data.type === 'tick') {
          const ticker = data.ticker || data.symbol;
          if (ticker) {
            setStockData(prev => ({
              ...prev,
              [ticker]: {
                price: data.price || data.last_price || prev[ticker]?.price || 0,
                rsi: data.rsi ?? prev[ticker]?.rsi ?? 50,
                change: data.change ?? prev[ticker]?.change ?? 0,
                volume_ratio: data.volume_ratio ?? prev[ticker]?.volume_ratio ?? 1,
                vwap_status: data.vwap_status ?? prev[ticker]?.vwap_status ?? 'neutral',
              }
            }));
          }
        }
      } catch (e) {
        console.error('Error parsing heatmap message:', e);
      }
    };

    websocket.addEventListener('message', handleMessage);
    return () => websocket.removeEventListener('message', handleMessage);
  }, [websocket]);

  const getRSIColor = (rsi) => {
    if (rsi === undefined || rsi === null) return 'bg-slate-700';
    if (rsi > 60) return 'bg-emerald-600';
    if (rsi < 40) return 'bg-red-600';
    return 'bg-slate-600';
  };

  const getRSITextColor = (rsi) => {
    if (rsi === undefined || rsi === null) return 'text-slate-400';
    if (rsi > 60) return 'text-emerald-400';
    if (rsi < 40) return 'text-red-400';
    return 'text-slate-300';
  };

  const getChangeColor = (change) => {
    if (change > 0) return 'text-emerald-400';
    if (change < 0) return 'text-red-400';
    return 'text-slate-400';
  };

  const isVolumeSpike = (volumeRatio) => volumeRatio > 3;

  return (
    <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
      <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
        <span className="text-2xl">🔥</span>
        Technical Heatmap
        <span className="text-sm font-normal text-slate-400">
          ({stocks.length} stocks)
        </span>
      </h3>

      {/* Legend */}
      <div className="flex gap-4 mb-4 text-xs">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded bg-emerald-600"></div>
          <span className="text-slate-400">RSI &gt; 60 (Bullish)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded bg-red-600"></div>
          <span className="text-slate-400">RSI &lt; 40 (Bearish)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded bg-slate-600"></div>
          <span className="text-slate-400">RSI 40-60 (Neutral)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded bg-yellow-500 animate-pulse"></div>
          <span className="text-slate-400">Volume Spike (&gt;3x)</span>
        </div>
      </div>

      {/* Heatmap Grid */}
      <div className="grid grid-cols-5 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10 gap-2">
        {stocks.map((ticker) => {
          const data = stockData[ticker] || {};
          const rsi = data.rsi;
          const price = data.price;
          const change = data.change || 0;
          const volumeRatio = data.volume_ratio || 1;
          const isSpike = isVolumeSpike(volumeRatio);
          const isSelected = selectedTicker === ticker;

          return (
            <HeatmapCell
              key={ticker}
              ticker={ticker}
              rsi={rsi}
              price={price}
              change={change}
              volumeRatio={volumeRatio}
              isSpike={isSpike}
              isSelected={isSelected}
              onClick={() => onSelectTicker?.(ticker)}
              getRSIColor={getRSIColor}
              getRSITextColor={getRSITextColor}
              getChangeColor={getChangeColor}
            />
          );
        })}
      </div>

      {/* Summary Stats */}
      <div className="mt-4 pt-4 border-t border-slate-700 grid grid-cols-3 gap-4 text-sm">
        <div className="text-center">
          <div className="text-emerald-400 text-xl font-bold">
            {Object.values(stockData).filter(s => s.rsi > 60).length}
          </div>
          <div className="text-slate-400">Bullish</div>
        </div>
        <div className="text-center">
          <div className="text-red-400 text-xl font-bold">
            {Object.values(stockData).filter(s => s.rsi < 40).length}
          </div>
          <div className="text-slate-400">Bearish</div>
        </div>
        <div className="text-center">
          <div className="text-yellow-400 text-xl font-bold">
            {Object.values(stockData).filter(s => s.volume_ratio > 3).length}
          </div>
          <div className="text-slate-400">Volume Spikes</div>
        </div>
      </div>
    </div>
  );
};

const HeatmapCell = ({
  ticker,
  rsi,
  price,
  change,
  volumeRatio,
  isSpike,
  isSelected,
  onClick,
  getRSIColor,
  getRSITextColor,
  getChangeColor,
}) => {
  const [showTooltip, setShowTooltip] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={onClick}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        className={`
          w-full aspect-square rounded-lg p-2 transition-all duration-200
          flex flex-col items-center justify-center
          ${getRSIColor(rsi)}
          ${isSelected ? 'ring-2 ring-cyan-400 ring-offset-2 ring-offset-slate-900' : ''}
          ${isSpike ? 'animate-pulse shadow-lg shadow-yellow-500/50' : ''}
          hover:scale-105 hover:z-10
        `}
      >
        {/* Ticker Symbol */}
        <span className="text-xs font-bold text-white truncate w-full text-center">
          {ticker.length > 6 ? ticker.slice(0, 5) + '..' : ticker}
        </span>
        
        {/* RSI Value */}
        <span className={`text-xs font-mono ${getRSITextColor(rsi)}`}>
          {rsi !== undefined ? rsi.toFixed(0) : '--'}
        </span>

        {/* Volume Spike Indicator */}
        {isSpike && (
          <span className="absolute -top-1 -right-1 w-3 h-3 bg-yellow-400 rounded-full animate-ping" />
        )}
      </button>

      {/* Tooltip */}
      {showTooltip && (
        <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-40 p-2 bg-slate-900 rounded-lg shadow-xl border border-slate-600 text-xs">
          <div className="font-bold text-white mb-1">{ticker}</div>
          <div className="grid grid-cols-2 gap-1 text-slate-300">
            <span>Price:</span>
            <span className="text-right font-mono">
              {price ? `₹${price.toFixed(2)}` : '--'}
            </span>
            
            <span>RSI:</span>
            <span className={`text-right font-mono ${getRSITextColor(rsi)}`}>
              {rsi?.toFixed(1) || '--'}
            </span>
            
            <span>Change:</span>
            <span className={`text-right font-mono ${getChangeColor(change)}`}>
              {change > 0 ? '+' : ''}{change.toFixed(2)}%
            </span>
            
            <span>Volume:</span>
            <span className={`text-right font-mono ${isSpike ? 'text-yellow-400' : ''}`}>
              {volumeRatio.toFixed(1)}x
            </span>
          </div>
          
          {/* Tooltip Arrow */}
          <div className="absolute top-full left-1/2 -translate-x-1/2 w-0 h-0 border-l-4 border-r-4 border-t-4 border-transparent border-t-slate-600" />
        </div>
      )}
    </div>
  );
};

export default Heatmap;
