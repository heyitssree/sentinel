import React, { useState, useEffect, useRef } from 'react';

const AIReasoningPanel = ({ ticker, onConfluenceUpdate }) => {
  const [confluence, setConfluence] = useState(null);
  const [sentiment, setSentiment] = useState(0);
  const [sentimentData, setSentimentData] = useState(null);
  const [reasoning, setReasoning] = useState([]);
  const [loading, setLoading] = useState(false);
  const reasoningEndRef = useRef(null);

  useEffect(() => {
    if (ticker) {
      fetchConfluence();
      fetchSentiment();
    }
  }, [ticker]);

  useEffect(() => {
    // Auto-scroll reasoning log
    reasoningEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [reasoning]);

  const fetchSentiment = async () => {
    if (!ticker) return;
    try {
      const response = await fetch(`/api/sentiment/${ticker}`);
      const data = await response.json();
      setSentimentData(data);
      setSentiment(data.score || 0);
      
      // Add sentiment to reasoning log
      if (data.reasoning) {
        setReasoning(prev => [...prev.slice(-20), 
          `[${new Date().toLocaleTimeString()}] Sentiment: ${data.recommendation} (${data.score?.toFixed(2)})`,
          `  → ${data.reasoning}`,
          data.source === 'mock' ? '  → (Using mock data)' : ''
        ].filter(Boolean));
      }
    } catch (error) {
      console.error('Failed to fetch sentiment:', error);
    }
  };

  const fetchConfluence = async () => {
    if (!ticker) return;
    setLoading(true);
    try {
      const response = await fetch(`/api/signals/${ticker}/confluence`);
      const data = await response.json();
      setConfluence(data);
      
      // Add to reasoning log with typewriter effect
      if (data.checks) {
        const newReasoning = [
          `[${new Date().toLocaleTimeString()}] Analyzing ${ticker}...`,
          `  → 200 EMA: ${data.checks.ema_200?.status} (${data.checks.ema_200?.value?.toFixed(2) || 'N/A'})`,
          `  → RSI(14): ${data.checks.rsi?.status} (${data.checks.rsi?.value?.toFixed(1) || 'N/A'})`,
          `  → VWAP: ${data.checks.vwap?.status} (${data.checks.vwap?.value?.toFixed(2) || 'N/A'})`,
          `  → Confluence: ${data.confluence_met ? '✓ MET' : '✗ NOT MET'}`,
          data.volume?.is_spike ? '  → ⚠️ VOLUME SPIKE DETECTED!' : '',
        ].filter(Boolean);
        
        setReasoning(prev => [...prev.slice(-20), ...newReasoning]);
      }
      
      if (onConfluenceUpdate) {
        onConfluenceUpdate(data);
      }
    } catch (error) {
      console.error('Failed to fetch confluence:', error);
    } finally {
      setLoading(false);
    }
  };

  // Sentiment gauge needle rotation (-90 to 90 degrees)
  const needleRotation = sentiment * 90;

  return (
    <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
      <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <span className="text-2xl">🤖</span>
        AI Reasoning Panel
        {loading && <span className="text-xs text-slate-400 animate-pulse">analyzing...</span>}
      </h3>

      {/* Sentiment Gauge */}
      <div className="mb-6">
        <div className="text-sm text-slate-400 mb-2">Gemini Sentiment Score</div>
        <div className="relative w-full h-24 flex justify-center">
          {/* Gauge background */}
          <div className="relative w-40 h-20 overflow-hidden">
            {/* Semi-circle background */}
            <div className="absolute bottom-0 w-40 h-20 rounded-t-full bg-gradient-to-r from-red-500 via-yellow-500 to-green-500 opacity-30" />
            
            {/* Gauge markers */}
            <div className="absolute bottom-0 left-0 text-xs text-red-400">-1</div>
            <div className="absolute bottom-0 left-1/2 -translate-x-1/2 text-xs text-yellow-400">0</div>
            <div className="absolute bottom-0 right-0 text-xs text-green-400">+1</div>
            
            {/* Needle */}
            <div 
              className="absolute bottom-0 left-1/2 w-1 h-16 bg-white rounded-full origin-bottom transition-transform duration-500 ease-out"
              style={{ transform: `translateX(-50%) rotate(${needleRotation}deg)` }}
            >
              <div className="w-3 h-3 bg-white rounded-full -mt-1 -ml-1" />
            </div>
            
            {/* Center dot */}
            <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-4 h-4 bg-slate-600 rounded-full border-2 border-white" />
          </div>
          
          {/* Current value */}
          <div className="absolute bottom-0 text-lg font-bold text-white">
            {sentiment.toFixed(2)}
          </div>
        </div>
        
        {/* Recommendation Badge */}
        {sentimentData?.recommendation && (
          <div className={`mt-2 text-center px-3 py-1 rounded-full text-sm font-bold ${
            sentimentData.recommendation === 'BULLISH' ? 'bg-green-500/20 text-green-400' :
            sentimentData.recommendation === 'BEARISH' ? 'bg-red-500/20 text-red-400' :
            'bg-yellow-500/20 text-yellow-400'
          }`}>
            {sentimentData.recommendation}
            {sentimentData.source === 'gemini' && <span className="ml-1 text-xs opacity-70">✨ Gemini</span>}
            {sentimentData.source === 'no_data' && <span className="ml-1 text-xs opacity-70">📰 No news</span>}
          </div>
        )}
        {sentimentData?.headlines_analyzed > 0 && (
          <div className="text-xs text-slate-500 text-center mt-1">
            Based on {sentimentData.headlines_analyzed} headline{sentimentData.headlines_analyzed > 1 ? 's' : ''}
          </div>
        )}
      </div>

      {/* Confluence Status Checkmarks */}
      <div className="mb-6">
        <div className="text-sm text-slate-400 mb-2">Confluence Status</div>
        <div className="grid grid-cols-3 gap-2">
          {/* 200 EMA Check */}
          <div className={`p-3 rounded-lg border ${
            confluence?.checks?.ema_200?.met 
              ? 'bg-green-900/30 border-green-500' 
              : 'bg-slate-700/50 border-slate-600'
          }`}>
            <div className="text-2xl text-center mb-1">
              {confluence?.checks?.ema_200?.met ? '✓' : '✗'}
            </div>
            <div className="text-xs text-center text-slate-300">200 EMA</div>
            <div className="text-xs text-center text-slate-500">
              {confluence?.checks?.ema_200?.value?.toFixed(0) || '—'}
            </div>
          </div>

          {/* RSI Check */}
          <div className={`p-3 rounded-lg border ${
            confluence?.checks?.rsi?.met 
              ? 'bg-green-900/30 border-green-500' 
              : 'bg-slate-700/50 border-slate-600'
          }`}>
            <div className="text-2xl text-center mb-1">
              {confluence?.checks?.rsi?.met ? '✓' : '✗'}
            </div>
            <div className="text-xs text-center text-slate-300">RSI &gt; 60</div>
            <div className="text-xs text-center text-slate-500">
              {confluence?.checks?.rsi?.value?.toFixed(1) || '—'}
            </div>
          </div>

          {/* VWAP Check */}
          <div className={`p-3 rounded-lg border ${
            confluence?.checks?.vwap?.met 
              ? 'bg-green-900/30 border-green-500' 
              : 'bg-slate-700/50 border-slate-600'
          }`}>
            <div className="text-2xl text-center mb-1">
              {confluence?.checks?.vwap?.met ? '✓' : '✗'}
            </div>
            <div className="text-xs text-center text-slate-300">VWAP</div>
            <div className="text-xs text-center text-slate-500">
              {confluence?.checks?.vwap?.value?.toFixed(0) || '—'}
            </div>
          </div>
        </div>

        {/* Overall confluence status */}
        <div className={`mt-3 p-2 rounded-lg text-center text-sm font-medium ${
          confluence?.confluence_met 
            ? 'bg-green-500/20 text-green-400 border border-green-500' 
            : 'bg-slate-700/50 text-slate-400 border border-slate-600'
        }`}>
          {confluence?.confluence_met 
            ? '🚀 CONFLUENCE MET - Ready for Audit' 
            : '⏳ Waiting for Confluence...'}
        </div>
      </div>

      {/* Reasoning Stream (Typewriter Log) */}
      <div className="mb-4">
        <div className="text-sm text-slate-400 mb-2">Reasoning Log</div>
        <div className="bg-slate-900 rounded-lg p-3 h-40 overflow-y-auto font-mono text-xs">
          {reasoning.length === 0 ? (
            <div className="text-slate-500 italic">
              Select a ticker to begin analysis...
            </div>
          ) : (
            reasoning.map((line, index) => (
              <div 
                key={index} 
                className={`text-slate-300 ${
                  line.includes('✓') ? 'text-green-400' : 
                  line.includes('✗') ? 'text-red-400' : 
                  line.includes('⚠️') ? 'text-yellow-400' : ''
                }`}
              >
                {line}
              </div>
            ))
          )}
          <div ref={reasoningEndRef} />
        </div>
      </div>

      {/* Volume Spike Indicator */}
      {confluence?.volume?.is_spike && (
        <div className="animate-pulse bg-yellow-500/20 border border-yellow-500 rounded-lg p-3 text-center">
          <span className="text-yellow-400 font-medium">
            ⚡ Volume Spike: {confluence.volume.ratio?.toFixed(1)}x average
          </span>
        </div>
      )}

      {/* Refresh Button */}
      <button
        onClick={fetchConfluence}
        disabled={loading || !ticker}
        className="mt-4 w-full py-2 px-4 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 
                   text-white rounded-lg text-sm transition-colors"
      >
        {loading ? 'Analyzing...' : 'Refresh Analysis'}
      </button>
    </div>
  );
};

export default AIReasoningPanel;
