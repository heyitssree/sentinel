import React, { useState, useEffect, useRef } from 'react';

const AIPanel = ({ websocket, ticker }) => {
  const [sentiment, setSentiment] = useState(0);
  const [confidence, setConfidence] = useState(0);
  const [bias, setBias] = useState('NEUTRAL');
  const [reasoningLogs, setReasoningLogs] = useState([]);
  const [confluence, setConfluence] = useState({
    ema_200: false,
    rsi_cross: false,
    vwap: false,
  });
  const [isTyping, setIsTyping] = useState(false);
  const logsEndRef = useRef(null);

  useEffect(() => {
    if (!websocket) return;

    const handleMessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        if (data.type === 'ai_reasoning') {
          setSentiment(data.sentiment || 0);
          setConfidence(data.confidence || 0);
          setBias(data.bias || 'NEUTRAL');
          
          if (data.confluence) {
            setConfluence(data.confluence);
          }
          
          if (data.logic) {
            addReasoningLog(data.ticker, data.logic);
          }
        }
      } catch (e) {
        console.error('Error parsing AI message:', e);
      }
    };

    websocket.addEventListener('message', handleMessage);
    return () => websocket.removeEventListener('message', handleMessage);
  }, [websocket]);

  const addReasoningLog = (tickerSymbol, logic) => {
    const timestamp = new Date().toLocaleTimeString();
    const newLog = { timestamp, ticker: tickerSymbol, logic, id: Date.now() };
    
    setReasoningLogs(prev => [...prev.slice(-50), newLog]);
    setIsTyping(true);
    
    setTimeout(() => setIsTyping(false), 1000);
  };

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [reasoningLogs]);

  const getSentimentColor = (value) => {
    if (value > 0.3) return '#00f5d4';
    if (value < -0.3) return '#ff6b6b';
    return '#ffd700';
  };

  const getBiasStyle = (biasValue) => {
    switch (biasValue) {
      case 'BULLISH':
        return { color: '#00f5d4', bg: 'rgba(0, 245, 212, 0.1)' };
      case 'BEARISH':
        return { color: '#ff6b6b', bg: 'rgba(255, 107, 107, 0.1)' };
      default:
        return { color: '#ffd700', bg: 'rgba(255, 215, 0, 0.1)' };
    }
  };

  const biasStyle = getBiasStyle(bias);
  const needleRotation = sentiment * 90;

  return (
    <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
      <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
        <span className="text-2xl">🤖</span>
        AI Reasoning Panel
        {ticker && <span className="text-sm text-slate-400">({ticker})</span>}
      </h3>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Sentiment Gauge */}
        <div className="bg-slate-900 rounded-lg p-4">
          <h4 className="text-sm font-semibold text-slate-400 mb-3">Sentiment Gauge</h4>
          
          <div className="relative w-full h-32 flex items-center justify-center">
            {/* Gauge Arc */}
            <svg viewBox="0 0 200 120" className="w-full h-full">
              {/* Background Arc */}
              <path
                d="M 20 100 A 80 80 0 0 1 180 100"
                fill="none"
                stroke="#374151"
                strokeWidth="12"
                strokeLinecap="round"
              />
              {/* Gradient Arc */}
              <defs>
                <linearGradient id="gaugeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#ff6b6b" />
                  <stop offset="50%" stopColor="#ffd700" />
                  <stop offset="100%" stopColor="#00f5d4" />
                </linearGradient>
              </defs>
              <path
                d="M 20 100 A 80 80 0 0 1 180 100"
                fill="none"
                stroke="url(#gaugeGradient)"
                strokeWidth="12"
                strokeLinecap="round"
                opacity="0.3"
              />
              {/* Needle */}
              <g transform={`rotate(${needleRotation}, 100, 100)`}>
                <line
                  x1="100"
                  y1="100"
                  x2="100"
                  y2="35"
                  stroke={getSentimentColor(sentiment)}
                  strokeWidth="3"
                  strokeLinecap="round"
                />
                <circle cx="100" cy="100" r="8" fill={getSentimentColor(sentiment)} />
              </g>
              {/* Labels */}
              <text x="20" y="115" fill="#9ca3af" fontSize="10">-1</text>
              <text x="95" y="25" fill="#9ca3af" fontSize="10">0</text>
              <text x="175" y="115" fill="#9ca3af" fontSize="10">+1</text>
            </svg>
          </div>

          <div className="text-center mt-2">
            <span 
              className="text-2xl font-bold"
              style={{ color: getSentimentColor(sentiment) }}
            >
              {sentiment >= 0 ? '+' : ''}{sentiment.toFixed(2)}
            </span>
            <span 
              className="ml-3 px-2 py-1 rounded text-sm font-semibold"
              style={{ backgroundColor: biasStyle.bg, color: biasStyle.color }}
            >
              {bias}
            </span>
          </div>

          {/* Confidence Bar */}
          <div className="mt-3">
            <div className="flex justify-between text-xs text-slate-400 mb-1">
              <span>Confidence</span>
              <span>{(confidence * 100).toFixed(0)}%</span>
            </div>
            <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
              <div 
                className="h-full rounded-full transition-all duration-500"
                style={{ 
                  width: `${confidence * 100}%`,
                  backgroundColor: confidence >= 0.8 ? '#00f5d4' : confidence >= 0.5 ? '#ffd700' : '#ff6b6b'
                }}
              />
            </div>
          </div>
        </div>

        {/* Confluence Status */}
        <div className="bg-slate-900 rounded-lg p-4">
          <h4 className="text-sm font-semibold text-slate-400 mb-3">Confluence Check</h4>
          
          <div className="space-y-3">
            <ConfluenceItem 
              label="200 EMA" 
              description="Price above trend line"
              active={confluence.ema_200} 
            />
            <ConfluenceItem 
              label="RSI Cross" 
              description="Momentum confirmed"
              active={confluence.rsi_cross} 
            />
            <ConfluenceItem 
              label="VWAP" 
              description="Volume price action"
              active={confluence.vwap} 
            />
          </div>

          <div className="mt-4 pt-3 border-t border-slate-700">
            <div className="flex justify-between items-center">
              <span className="text-sm text-slate-400">Conditions Met</span>
              <span className="text-lg font-bold" style={{
                color: Object.values(confluence).filter(Boolean).length === 3 ? '#00f5d4' : '#ffd700'
              }}>
                {Object.values(confluence).filter(Boolean).length} / 3
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Reasoning Logs */}
      <div className="mt-4 bg-slate-900 rounded-lg p-4">
        <h4 className="text-sm font-semibold text-slate-400 mb-3 flex items-center gap-2">
          <span>📝</span>
          Reasoning Logs
          {isTyping && <span className="animate-pulse text-cyan-400">●</span>}
        </h4>
        
        <div className="h-40 overflow-y-auto font-mono text-xs space-y-1 scrollbar-thin scrollbar-thumb-slate-600">
          {reasoningLogs.length === 0 ? (
            <div className="text-slate-500 italic">Waiting for AI analysis...</div>
          ) : (
            reasoningLogs.map((log) => (
              <div 
                key={log.id} 
                className="text-slate-300 py-1 border-b border-slate-800 animate-fadeIn"
              >
                <span className="text-slate-500">[{log.timestamp}]</span>
                <span className="text-cyan-400 ml-2">{log.ticker}:</span>
                <span className="ml-2">{log.logic}</span>
              </div>
            ))
          )}
          <div ref={logsEndRef} />
        </div>
      </div>
    </div>
  );
};

const ConfluenceItem = ({ label, description, active }) => (
  <div className={`
    flex items-center justify-between p-2 rounded-lg transition-all duration-300
    ${active ? 'bg-cyan-900/20 border border-cyan-500/30' : 'bg-slate-800 border border-slate-700'}
  `}>
    <div className="flex items-center gap-3">
      <span className={`
        w-6 h-6 rounded-full flex items-center justify-center text-sm
        ${active ? 'bg-cyan-500 text-slate-900' : 'bg-slate-700 text-slate-500'}
      `}>
        {active ? '✓' : '○'}
      </span>
      <div>
        <div className={`font-medium ${active ? 'text-cyan-400' : 'text-slate-400'}`}>
          {label}
        </div>
        <div className="text-xs text-slate-500">{description}</div>
      </div>
    </div>
  </div>
);

export default AIPanel;
