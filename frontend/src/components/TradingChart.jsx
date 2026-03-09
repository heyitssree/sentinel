import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CrosshairMode } from 'lightweight-charts';

const TradingChart = ({ 
  ticker, 
  candles = [], 
  indicators = {},
  position = null,
  trades = [],
  height = 400 
}) => {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const vwapLineRef = useRef(null);
  const ema200LineRef = useRef(null);
  const ema20LineRef = useRef(null);
  const ema9LineRef = useRef(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#1a1a2e' },
        textColor: '#d1d5db',
      },
      grid: {
        vertLines: { color: '#2d2d44' },
        horzLines: { color: '#2d2d44' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: '#4361ee',
          width: 1,
          style: 2,
          labelBackgroundColor: '#4361ee',
        },
        horzLine: {
          color: '#4361ee',
          width: 1,
          style: 2,
          labelBackgroundColor: '#4361ee',
        },
      },
      rightPriceScale: {
        borderColor: '#2d2d44',
        scaleMargins: { top: 0.1, bottom: 0.2 },
      },
      timeScale: {
        borderColor: '#2d2d44',
        timeVisible: true,
        secondsVisible: false,
      },
      width: chartContainerRef.current.clientWidth,
      height: height,
    });

    chartRef.current = chart;

    // Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#00f5d4',
      downColor: '#ff6b6b',
      borderUpColor: '#00f5d4',
      borderDownColor: '#ff6b6b',
      wickUpColor: '#00f5d4',
      wickDownColor: '#ff6b6b',
    });
    candleSeriesRef.current = candleSeries;

    // VWAP line (blue dashed)
    const vwapLine = chart.addLineSeries({
      color: '#4361ee',
      lineWidth: 2,
      lineStyle: 2, // Dashed
      title: 'VWAP',
    });
    vwapLineRef.current = vwapLine;

    // 200 EMA line (purple - trend)
    const ema200Line = chart.addLineSeries({
      color: '#9d4edd',
      lineWidth: 2,
      title: '200 EMA',
    });
    ema200LineRef.current = ema200Line;

    // 20 EMA line (orange)
    const ema20Line = chart.addLineSeries({
      color: '#ff6b35',
      lineWidth: 1,
      title: '20 EMA',
    });
    ema20LineRef.current = ema20Line;

    // 9 EMA line (cyan - trailing)
    const ema9Line = chart.addLineSeries({
      color: '#00f5d4',
      lineWidth: 1,
      lineStyle: 1, // Dotted
      title: '9 EMA',
    });
    ema9LineRef.current = ema9Line;

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    setIsLoading(false);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [height]);

  // Update candle data
  useEffect(() => {
    if (!candleSeriesRef.current || candles.length === 0) return;

    const formattedCandles = candles.map(c => ({
      time: c.time || (typeof c.timestamp === 'string' 
        ? Math.floor(new Date(c.timestamp).getTime() / 1000)
        : c.timestamp),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    // Sort by time and remove duplicates
    const uniqueCandles = formattedCandles
      .sort((a, b) => a.time - b.time)
      .filter((c, i, arr) => i === 0 || c.time !== arr[i - 1].time);

    candleSeriesRef.current.setData(uniqueCandles);
    chartRef.current?.timeScale().fitContent();
  }, [candles]);

  // Update VWAP
  useEffect(() => {
    if (!vwapLineRef.current || !indicators.vwap) return;

    // API returns array of {time, value} objects - sort and deduplicate
    const formattedVwap = indicators.vwap
      .filter(v => v && v.value != null && !isNaN(v.value))
      .sort((a, b) => a.time - b.time)
      .filter((v, i, arr) => i === 0 || v.time !== arr[i - 1].time);

    vwapLineRef.current.setData(formattedVwap);
  }, [indicators.vwap]);

  // Update EMAs
  useEffect(() => {
    // Format indicator data - API returns array of {time, value} objects
    const formatIndicator = (data) => {
      if (!data || !Array.isArray(data)) return [];
      return data
        .filter(v => v && v.value != null && !isNaN(v.value))
        .sort((a, b) => a.time - b.time)
        .filter((v, i, arr) => i === 0 || v.time !== arr[i - 1].time);
    };

    if (ema200LineRef.current && indicators.ema_200) {
      ema200LineRef.current.setData(formatIndicator(indicators.ema_200));
    }
    if (ema20LineRef.current && indicators.ema_20) {
      ema20LineRef.current.setData(formatIndicator(indicators.ema_20));
    }
    if (ema9LineRef.current && indicators.ema_9) {
      ema9LineRef.current.setData(formatIndicator(indicators.ema_9));
    }
  }, [indicators]);

  // Add position markers
  useEffect(() => {
    if (!candleSeriesRef.current || !position) return;

    const markers = [];

    if (position.entry_price) {
      // Add entry marker
      const lastCandle = candles[candles.length - 1];
      markers.push({
        time: position.entry_time 
          ? Math.floor(new Date(position.entry_time).getTime() / 1000)
          : (lastCandle?.time || lastCandle?.timestamp),
        position: 'belowBar',
        color: '#00ff00',
        shape: 'arrowUp',
        text: `Entry ₹${position.entry_price.toFixed(2)}`,
      });
    }

    // Add price lines for SL/TP
    if (position.stop_loss) {
      candleSeriesRef.current.createPriceLine({
        price: position.stop_loss,
        color: '#ff0000',
        lineWidth: 2,
        lineStyle: 2,
        axisLabelVisible: true,
        title: 'SL',
      });
    }

    if (position.take_profit) {
      candleSeriesRef.current.createPriceLine({
        price: position.take_profit,
        color: '#00ff00',
        lineWidth: 2,
        lineStyle: 2,
        axisLabelVisible: true,
        title: 'TP',
      });
    }

    if (markers.length > 0) {
      candleSeriesRef.current.setMarkers(markers);
    }
  }, [position, candles]);

  // Add trade markers
  useEffect(() => {
    if (!candleSeriesRef.current || trades.length === 0) return;

    const markers = trades.map(trade => ({
      time: Math.floor(new Date(trade.timestamp || trade.entry_time).getTime() / 1000),
      position: trade.side === 'BUY' ? 'belowBar' : 'aboveBar',
      color: trade.side === 'BUY' ? '#00f5d4' : '#ff6b6b',
      shape: trade.side === 'BUY' ? 'arrowUp' : 'arrowDown',
      text: `${trade.side} ₹${trade.price?.toFixed(2) || trade.entry_price?.toFixed(2)}`,
    }));

    candleSeriesRef.current.setMarkers(markers);
  }, [trades]);

  return (
    <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
      <div className="flex justify-between items-center mb-3">
        <h3 className="text-lg font-bold text-white flex items-center gap-2">
          <span className="text-2xl">📈</span>
          {ticker || 'Chart'}
          <span className="text-sm font-normal text-slate-400">5min</span>
        </h3>
        
        {/* Legend */}
        <div className="flex gap-4 text-xs">
          <LegendItem color="#4361ee" label="VWAP" dashed />
          <LegendItem color="#9d4edd" label="200 EMA" />
          <LegendItem color="#ff6b35" label="20 EMA" />
          <LegendItem color="#00f5d4" label="9 EMA" dotted />
        </div>
      </div>

      <div className="relative">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-900/50 z-10">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-400"></div>
          </div>
        )}
        <div ref={chartContainerRef} />
      </div>

      {/* Position Info */}
      {position && (
        <div className="mt-3 p-3 bg-slate-900 rounded-lg grid grid-cols-4 gap-4 text-sm">
          <div>
            <span className="text-slate-400">Entry</span>
            <div className="text-white font-mono">₹{position.entry_price?.toFixed(2)}</div>
          </div>
          <div>
            <span className="text-slate-400">Stop Loss</span>
            <div className="text-red-400 font-mono">₹{position.stop_loss?.toFixed(2)}</div>
          </div>
          <div>
            <span className="text-slate-400">Take Profit</span>
            <div className="text-green-400 font-mono">₹{position.take_profit?.toFixed(2)}</div>
          </div>
          <div>
            <span className="text-slate-400">Qty</span>
            <div className="text-white font-mono">{position.quantity}</div>
          </div>
        </div>
      )}
    </div>
  );
};

const LegendItem = ({ color, label, dashed, dotted }) => (
  <div className="flex items-center gap-1">
    <div 
      className="w-4 h-0.5" 
      style={{ 
        backgroundColor: color,
        borderStyle: dashed ? 'dashed' : dotted ? 'dotted' : 'solid',
        borderWidth: dashed || dotted ? '1px 0 0 0' : '0',
        borderColor: color,
        height: dashed || dotted ? '0' : '2px',
      }}
    />
    <span className="text-slate-400">{label}</span>
  </div>
);

export default TradingChart;
