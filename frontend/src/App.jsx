import React, { useState, useEffect, useCallback, useRef } from 'react';
import { 
  Shield, Activity, TrendingUp, TrendingDown, DollarSign, 
  AlertTriangle, Play, Square, Zap, BarChart3, Newspaper,
  RefreshCw, XCircle, CheckCircle, Clock, Plus, Minus, 
  Wallet, PieChart, Settings, RotateCcw, Key, Loader2, Eye, EyeOff,
  LayoutGrid, Brain, FileText, CandlestickChart
} from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, AreaChart, Area } from 'recharts';

import AIReasoningPanel from './components/AIReasoningPanel';
import TechnicalHeatmap from './components/TechnicalHeatmap';
import TradingChart from './components/TradingChart';
import DailyAutopsy from './components/DailyAutopsy';

const API_BASE = '/api';

function App() {
  const [status, setStatus] = useState(null);
  const [positions, setPositions] = useState([]);
  const [trades, setTrades] = useState([]);
  const [selectedTicker, setSelectedTicker] = useState('RELIANCE');
  const [signals, setSignals] = useState({});
  const [wsConnected, setWsConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [availableStocks, setAvailableStocks] = useState([]);
  const [capitalInput, setCapitalInput] = useState('');
  const [customTicker, setCustomTicker] = useState('');
  const [activeView, setActiveView] = useState('dashboard'); // dashboard, heatmap, chart, autopsy
  const [chartData, setChartData] = useState({ candles: [], indicators: {} });
  const [tradingPhase, setTradingPhase] = useState(null);
  
  // Credentials state
  const [credentials, setCredentials] = useState(null);
  const [geminiKey, setGeminiKey] = useState('');
  const [zerodhaKey, setZerodhaKey] = useState('');
  const [zerodhaSecret, setZerodhaSecret] = useState('');
  const [showGeminiKey, setShowGeminiKey] = useState(false);
  const [showZerodhaKey, setShowZerodhaKey] = useState(false);
  const [testingGemini, setTestingGemini] = useState(false);
  const [testingZerodha, setTestingZerodha] = useState(false);
  const [geminiTestResult, setGeminiTestResult] = useState(null);
  const [zerodhaTestResult, setZerodhaTestResult] = useState(null);
  
  // Toast notification state
  const [toasts, setToasts] = useState([]);
  
  // Show toast notification
  const showToast = useCallback((title, message, type = 'info') => {
    const id = Date.now();
    setToasts(prev => [...prev, { id, title, message, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 5000);
  }, []);

  // Fetch initial data
  const fetchData = useCallback(async () => {
    try {
      const [statusRes, positionsRes, tradesRes, watchlistRes] = await Promise.all([
        fetch(`${API_BASE}/status`),
        fetch(`${API_BASE}/positions`),
        fetch(`${API_BASE}/trades?limit=20`),
        fetch(`${API_BASE}/watchlist`)
      ]);
      
      setStatus(await statusRes.json());
      setPositions((await positionsRes.json()).positions);
      setTrades((await tradesRes.json()).trades);
      const wlData = await watchlistRes.json();
      setAvailableStocks(wlData.available || []);
      setLoading(false);
    } catch (error) {
      console.error('Error fetching data:', error);
      setLoading(false);
    }
  }, []);

  // Fetch signals for selected ticker
  const fetchSignals = useCallback(async (ticker) => {
    try {
      const res = await fetch(`${API_BASE}/signals/${ticker}`);
      const data = await res.json();
      setSignals(prev => ({ ...prev, [ticker]: data }));
    } catch (error) {
      console.error('Error fetching signals:', error);
    }
  }, []);

  // Fetch chart data for selected ticker
  const fetchChartData = useCallback(async (ticker) => {
    try {
      const res = await fetch(`${API_BASE}/chart-data/${ticker}?interval=5min&limit=100`);
      const data = await res.json();
      setChartData(data);
    } catch (error) {
      console.error('Error fetching chart data:', error);
    }
  }, []);

  // Fetch trading phase
  const fetchTradingPhase = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/schedule/phase`);
      const data = await res.json();
      setTradingPhase(data);
    } catch (error) {
      console.error('Error fetching trading phase:', error);
    }
  }, []);

  // WebSocket connection with exponential backoff
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const reconnectAttemptRef = useRef(0);
  const maxReconnectAttempts = 10;
  const baseReconnectDelay = 1000;

  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    
    const ws = new WebSocket(`ws://${window.location.hostname}:8000/ws`);
    wsRef.current = ws;
    
    ws.onopen = () => {
      setWsConnected(true);
      reconnectAttemptRef.current = 0;
      console.log('WebSocket connected');
    };
    
    ws.onclose = (event) => {
      setWsConnected(false);
      wsRef.current = null;
      
      // Don't reconnect if closed cleanly or max attempts reached
      if (event.code === 1000 || reconnectAttemptRef.current >= maxReconnectAttempts) return;
      
      // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s (max)
      const delay = Math.min(baseReconnectDelay * Math.pow(2, reconnectAttemptRef.current), 32000);
      reconnectAttemptRef.current++;
      console.log(`WebSocket reconnecting in ${delay}ms (attempt ${reconnectAttemptRef.current})`);
      
      reconnectTimeoutRef.current = setTimeout(connectWebSocket, delay);
    };
    
    ws.onerror = () => setWsConnected(false);
    
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'tick') {
          setStatus(prev => ({
            ...prev,
            prices: data.prices,
            stats: data.stats,
            running: data.running
          }));
        } else if (data.type === 'trade_executed' || data.type === 'position_closed') {
          fetchData();
          // Show toast notification for trades
          showToast(
            data.type === 'trade_executed' ? 'Trade Executed' : 'Position Closed',
            `${data.ticker || 'Unknown'} - ${data.side || data.type}`,
            data.type === 'trade_executed' ? 'success' : 'info'
          );
        }
      } catch (e) {
        console.error('WebSocket message parse error:', e);
      }
    };
  }, [fetchData]);

  useEffect(() => {
    fetchData();
    connectWebSocket();
    
    const interval = setInterval(fetchData, 5000);
    
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) wsRef.current.close(1000);
      clearInterval(interval);
    };
  }, [fetchData, connectWebSocket]);

  // Fetch signals when ticker changes
  useEffect(() => {
    fetchSignals(selectedTicker);
    fetchChartData(selectedTicker);
  }, [selectedTicker, fetchSignals, fetchChartData]);

  // Fetch trading phase periodically
  useEffect(() => {
    fetchTradingPhase();
    const interval = setInterval(fetchTradingPhase, 60000); // Every minute
    return () => clearInterval(interval);
  }, [fetchTradingPhase]);

  // Control engine
  const controlEngine = async (action) => {
    try {
      console.log(`Engine control: ${action}`);
      const response = await fetch(`${API_BASE}/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
      });
      const result = await response.json();
      console.log(`Engine control result:`, result);
      if (!response.ok) {
        showToast('Error', result.detail || 'Failed to control engine', 'error');
      } else {
        showToast('Success', `Engine ${action} successful`, 'success');
      }
      fetchData();
    } catch (error) {
      console.error('Error controlling engine:', error);
      showToast('Error', `Failed to ${action} engine: ${error.message}`, 'error');
    }
  };

  // Watchlist management
  const addToWatchlist = async (ticker) => {
    try {
      await fetch(`${API_BASE}/watchlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, action: 'add' })
      });
      fetchData();
    } catch (error) {
      console.error('Error adding to watchlist:', error);
    }
  };

  const removeFromWatchlist = async (ticker) => {
    try {
      await fetch(`${API_BASE}/watchlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, action: 'remove' })
      });
      fetchData();
    } catch (error) {
      console.error('Error removing from watchlist:', error);
    }
  };

  const addCustomStock = async () => {
    const ticker = customTicker.trim().toUpperCase();
    if (!ticker) return;
    if (ticker.length < 2 || ticker.length > 20) {
      showToast('Invalid Ticker', 'Ticker must be 2-20 characters', 'error');
      return;
    }
    if (status?.watchlist?.includes(ticker)) {
      showToast('Duplicate', `${ticker} is already in watchlist`, 'warning');
      return;
    }
    await addToWatchlist(ticker);
    setCustomTicker('');
  };

  // Portfolio management
  const setCapital = async () => {
    const amount = parseFloat(capitalInput);
    if (isNaN(amount) || amount < 10000) {
      showToast('Invalid Amount', 'Minimum capital is ₹10,000', 'error');
      return;
    }
    try {
      await fetch(`${API_BASE}/portfolio/capital`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount })
      });
      setCapitalInput('');
      fetchData();
    } catch (error) {
      console.error('Error setting capital:', error);
    }
  };

  const resetPortfolio = async () => {
    if (!confirm('Reset portfolio? This will clear all holdings and reset to starting capital.')) return;
    try {
      await fetch(`${API_BASE}/portfolio/reset`, { method: 'POST' });
      fetchData();
    } catch (error) {
      console.error('Error resetting portfolio:', error);
    }
  };

  // Fetch credentials status
  const fetchCredentials = async () => {
    try {
      const res = await fetch(`${API_BASE}/credentials/status`);
      setCredentials(await res.json());
    } catch (error) {
      console.error('Error fetching credentials:', error);
    }
  };

  // Test Gemini connection
  const testGemini = async () => {
    setTestingGemini(true);
    setGeminiTestResult(null);
    try {
      const res = await fetch(`${API_BASE}/credentials/test/gemini`, { method: 'POST' });
      setGeminiTestResult(await res.json());
    } catch (error) {
      setGeminiTestResult({ success: false, error: error.message });
    }
    setTestingGemini(false);
  };

  // Test Zerodha connection
  const testZerodha = async () => {
    setTestingZerodha(true);
    setZerodhaTestResult(null);
    try {
      const res = await fetch(`${API_BASE}/credentials/test/zerodha`, { method: 'POST' });
      setZerodhaTestResult(await res.json());
    } catch (error) {
      setZerodhaTestResult({ success: false, error: error.message });
    }
    setTestingZerodha(false);
  };

  // Update Gemini key
  const updateGeminiKey = async () => {
    if (!geminiKey.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/credentials/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential_type: 'gemini', api_key: geminiKey })
      });
      const data = await res.json();
      if (data.success) {
        setGeminiKey('');
        fetchCredentials();
        showToast('Success', 'Gemini API key updated successfully', 'success');
      }
    } catch (error) {
      console.error('Error updating Gemini key:', error);
    }
  };

  // Update Zerodha credentials
  const updateZerodhaCredentials = async () => {
    if (!zerodhaKey.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/credentials/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          credential_type: 'zerodha', 
          api_key: zerodhaKey,
          api_secret: zerodhaSecret || undefined
        })
      });
      const data = await res.json();
      if (data.success) {
        setZerodhaKey('');
        setZerodhaSecret('');
        fetchCredentials();
        showToast('Success', 'Zerodha credentials updated successfully', 'success');
      }
    } catch (error) {
      console.error('Error updating Zerodha credentials:', error);
    }
  };

  // Fetch credentials when settings open
  useEffect(() => {
    if (showSettings) {
      fetchCredentials();
    }
  }, [showSettings]);

  // Execute trade
  const executeTrade = async (ticker, side) => {
    try {
      const res = await fetch(`${API_BASE}/trade`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, side })
      });
      const data = await res.json();
      if (data.success) {
        showToast('Trade Executed', `${side} ${ticker} @ ₹${data.price?.toFixed(2) || 'N/A'}`, 'success');
      } else {
        showToast('Trade Failed', data.error || 'Unknown error', 'error');
      }
      fetchData();
    } catch (error) {
      showToast('Trade Error', error.message, 'error');
      console.error('Error executing trade:', error);
    }
  };

  // Close position
  const closePosition = async (ticker) => {
    try {
      const res = await fetch(`${API_BASE}/close/${ticker}`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        showToast('Position Closed', `${ticker} closed with P&L: ₹${data.pnl?.toFixed(2) || 'N/A'}`, 
          (data.pnl || 0) >= 0 ? 'success' : 'warning');
      } else {
        showToast('Close Failed', data.error || 'Unknown error', 'error');
      }
      fetchData();
    } catch (error) {
      showToast('Close Error', error.message, 'error');
      console.error('Error closing position:', error);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-sentinel-dark flex items-center justify-center">
        <div className="text-center">
          <Shield className="w-16 h-16 text-blue-500 mx-auto animate-pulse" />
          <p className="text-gray-400 mt-4">Loading The Sentinel...</p>
        </div>
      </div>
    );
  }

  const riskPercent = status?.risk ? (status.risk.mtm_loss / status.risk.limit) * 100 : 0;

  return (
    <div className="min-h-screen bg-sentinel-dark text-white p-6">
      {/* Toast Notifications */}
      <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2">
        {toasts.map(toast => (
          <div 
            key={toast.id}
            className={`px-4 py-3 rounded-lg shadow-lg border animate-slide-in-right flex items-start gap-3 min-w-[300px] ${
              toast.type === 'success' ? 'bg-green-900/90 border-green-500/50 text-green-100' :
              toast.type === 'error' ? 'bg-red-900/90 border-red-500/50 text-red-100' :
              toast.type === 'warning' ? 'bg-yellow-900/90 border-yellow-500/50 text-yellow-100' :
              'bg-blue-900/90 border-blue-500/50 text-blue-100'
            }`}
          >
            <div className="flex-shrink-0 mt-0.5">
              {toast.type === 'success' ? <CheckCircle className="w-5 h-5" /> :
               toast.type === 'error' ? <XCircle className="w-5 h-5" /> :
               toast.type === 'warning' ? <AlertTriangle className="w-5 h-5" /> :
               <Activity className="w-5 h-5" />}
            </div>
            <div>
              <p className="font-semibold text-sm">{toast.title}</p>
              <p className="text-xs opacity-80">{toast.message}</p>
            </div>
            <button 
              onClick={() => setToasts(prev => prev.filter(t => t.id !== toast.id))}
              className="ml-auto opacity-60 hover:opacity-100"
            >
              <XCircle className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>

      {/* Header - Mobile Responsive */}
      <header className="flex flex-col sm:flex-row items-start sm:items-center justify-between mb-6 md:mb-8 gap-4">
        <div className="flex items-center gap-3 md:gap-4">
          <Shield className="w-8 h-8 md:w-10 md:h-10 text-blue-500" />
          <div>
            <h1 className="text-xl md:text-2xl font-bold">The Sentinel</h1>
            <p className="text-gray-400 text-xs md:text-sm">Multimodal Alpha Engine</p>
          </div>
        </div>
        
        <div className="flex flex-wrap items-center gap-2 md:gap-4 w-full sm:w-auto">
          {/* Connection Status */}
          <div className={`flex items-center gap-2 px-2 md:px-3 py-1 rounded-full text-xs md:text-sm ${wsConnected ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
            <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-green-500 pulse-green' : 'bg-red-500 pulse-red'}`} />
            <span className="hidden xs:inline">{wsConnected ? 'Connected' : 'Disconnected'}</span>
          </div>
          
          {/* Engine Controls - Compact on mobile */}
          <div className="flex gap-1 md:gap-2 flex-wrap">
            <button 
              onClick={() => setShowSettings(true)}
              className="flex items-center gap-1 md:gap-2 px-2 md:px-4 py-1.5 md:py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition text-sm"
            >
              <Settings className="w-4 h-4" />
            </button>
            <button 
              onClick={() => controlEngine('start')}
              disabled={status?.running}
              className="flex items-center gap-1 md:gap-2 px-2 md:px-4 py-1.5 md:py-2 bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition text-sm"
            >
              <Play className="w-4 h-4" /> <span className="hidden md:inline">Start</span>
            </button>
            <button 
              onClick={() => controlEngine('stop')}
              disabled={!status?.running}
              className="flex items-center gap-1 md:gap-2 px-2 md:px-4 py-1.5 md:py-2 bg-gray-600 hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition text-sm"
            >
              <Square className="w-4 h-4" /> <span className="hidden md:inline">Stop</span>
            </button>
            <button 
              onClick={() => controlEngine('emergency_stop')}
              className="flex items-center gap-1 md:gap-2 px-2 md:px-4 py-1.5 md:py-2 bg-red-600 hover:bg-red-700 rounded-lg transition text-sm"
            >
              <Zap className="w-4 h-4" /> <span className="hidden lg:inline">Emergency</span>
            </button>
          </div>
        </div>
      </header>

      {/* Settings Modal */}
      {showSettings && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-sentinel-card border border-sentinel-border rounded-xl p-6 w-full max-w-2xl max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold flex items-center gap-2">
                <Settings className="w-5 h-5" /> Settings
              </h2>
              <button onClick={() => setShowSettings(false)} className="text-gray-400 hover:text-white">
                <XCircle className="w-6 h-6" />
              </button>
            </div>

            {/* Capital Settings */}
            <div className="mb-6">
              <h3 className="font-semibold mb-3 flex items-center gap-2">
                <Wallet className="w-4 h-4 text-blue-400" /> Paper Trading Capital
              </h3>
              <div className="bg-gray-700/50 rounded-lg p-4">
                <p className="text-sm text-gray-400 mb-2">
                  Current: ₹{status?.portfolio?.starting_capital?.toLocaleString('en-IN') || '100,000'}
                </p>
                <div className="flex gap-2">
                  <input
                    type="number"
                    value={capitalInput}
                    onChange={(e) => setCapitalInput(e.target.value)}
                    placeholder="Enter amount (min ₹10,000)"
                    className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-white"
                  />
                  <button onClick={setCapital} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg">
                    Set Capital
                  </button>
                </div>
                <button 
                  onClick={resetPortfolio}
                  className="mt-3 flex items-center gap-2 text-sm text-red-400 hover:text-red-300"
                >
                  <RotateCcw className="w-4 h-4" /> Reset Portfolio
                </button>
              </div>
            </div>

            {/* Watchlist Management */}
            <div>
              <h3 className="font-semibold mb-3 flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-green-400" /> Watchlist Management
              </h3>
              
              {/* Current Watchlist */}
              <div className="bg-gray-700/50 rounded-lg p-4 mb-4">
                <p className="text-sm text-gray-400 mb-2">Current Watchlist ({status?.watchlist?.length || 0}/10)</p>
                <div className="flex flex-wrap gap-2">
                  {status?.watchlist?.map(ticker => (
                    <span key={ticker} className="flex items-center gap-1 bg-blue-500/20 text-blue-400 px-3 py-1 rounded-full text-sm">
                      {ticker}
                      <button 
                        onClick={() => removeFromWatchlist(ticker)}
                        className="hover:text-red-400 ml-1"
                        disabled={status?.watchlist?.length <= 1}
                      >
                        <Minus className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
              </div>

              {/* Available Stocks */}
              <div className="bg-gray-700/50 rounded-lg p-4">
                <p className="text-sm text-gray-400 mb-2">Add Stocks</p>
                
                {/* Manual Stock Input */}
                <div className="flex gap-2 mb-3">
                  <input
                    type="text"
                    value={customTicker}
                    onChange={(e) => setCustomTicker(e.target.value.toUpperCase())}
                    onKeyDown={(e) => e.key === 'Enter' && addCustomStock()}
                    placeholder="Enter any NSE ticker (e.g., TATASTEEL)"
                    className="flex-1 bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm focus:outline-none focus:border-cyan-500"
                    maxLength={20}
                  />
                  <button
                    onClick={addCustomStock}
                    disabled={!customTicker.trim() || status?.watchlist?.length >= 10}
                    className="bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium transition flex items-center gap-1"
                  >
                    <Plus className="w-4 h-4" /> Add
                  </button>
                </div>
                
                {/* Preset Stocks */}
                <p className="text-xs text-gray-500 mb-2">Quick Add (Nifty 50):</p>
                <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto">
                  {availableStocks.map(ticker => (
                    <button
                      key={ticker}
                      onClick={() => addToWatchlist(ticker)}
                      disabled={status?.watchlist?.length >= 10}
                      className="flex items-center gap-1 bg-gray-600 hover:bg-gray-500 disabled:opacity-50 px-2 py-1 rounded-full text-xs transition"
                    >
                      <Plus className="w-3 h-3" /> {ticker}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* API Credentials */}
            <div className="mt-6 pt-6 border-t border-sentinel-border">
              <h3 className="font-semibold mb-4 flex items-center gap-2">
                <Key className="w-4 h-4 text-yellow-400" /> API Credentials
              </h3>

              {/* Gemini API */}
              <div className="bg-gray-700/50 rounded-lg p-4 mb-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">Gemini API</span>
                    {credentials?.gemini?.configured ? (
                      <span className="text-xs bg-green-500/20 text-green-400 px-2 py-0.5 rounded">Configured</span>
                    ) : (
                      <span className="text-xs bg-red-500/20 text-red-400 px-2 py-0.5 rounded">Not Set</span>
                    )}
                  </div>
                  <span className="text-sm text-gray-400 font-mono">{credentials?.gemini?.masked}</span>
                </div>
                
                <div className="flex gap-2 mb-3">
                  <div className="flex-1 relative">
                    <input
                      type={showGeminiKey ? "text" : "password"}
                      value={geminiKey}
                      onChange={(e) => setGeminiKey(e.target.value)}
                      placeholder="Enter Gemini API key"
                      className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-white pr-10"
                    />
                    <button 
                      onClick={() => setShowGeminiKey(!showGeminiKey)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white"
                    >
                      {showGeminiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  <button 
                    onClick={updateGeminiKey}
                    disabled={!geminiKey.trim()}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg"
                  >
                    Save
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  <button 
                    onClick={testGemini}
                    disabled={testingGemini}
                    className="flex items-center gap-2 px-3 py-1.5 bg-gray-600 hover:bg-gray-500 rounded-lg text-sm"
                  >
                    {testingGemini ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                    Test Connection
                  </button>
                  {geminiTestResult && (
                    <span className={`text-sm ${geminiTestResult.success ? 'text-green-400' : 'text-red-400'}`}>
                      {geminiTestResult.success ? '✓ ' + geminiTestResult.message : '✗ ' + geminiTestResult.error}
                    </span>
                  )}
                </div>
              </div>

              {/* Zerodha API */}
              <div className="bg-gray-700/50 rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">Zerodha Kite API</span>
                    {credentials?.zerodha?.configured ? (
                      <span className="text-xs bg-green-500/20 text-green-400 px-2 py-0.5 rounded">Configured</span>
                    ) : (
                      <span className="text-xs bg-yellow-500/20 text-yellow-400 px-2 py-0.5 rounded">Paper Mode</span>
                    )}
                  </div>
                  <span className="text-sm text-gray-400 font-mono">{credentials?.zerodha?.api_key_masked}</span>
                </div>
                
                <div className="space-y-2 mb-3">
                  <div className="flex gap-2">
                    <div className="flex-1 relative">
                      <input
                        type={showZerodhaKey ? "text" : "password"}
                        value={zerodhaKey}
                        onChange={(e) => setZerodhaKey(e.target.value)}
                        placeholder="API Key"
                        className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-white pr-10"
                      />
                      <button 
                        onClick={() => setShowZerodhaKey(!showZerodhaKey)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white"
                      >
                        {showZerodhaKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={zerodhaSecret}
                      onChange={(e) => setZerodhaSecret(e.target.value)}
                      placeholder="API Secret (optional)"
                      className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-white"
                    />
                    <button 
                      onClick={updateZerodhaCredentials}
                      disabled={!zerodhaKey.trim()}
                      className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg"
                    >
                      Save
                    </button>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button 
                    onClick={testZerodha}
                    disabled={testingZerodha}
                    className="flex items-center gap-2 px-3 py-1.5 bg-gray-600 hover:bg-gray-500 rounded-lg text-sm"
                  >
                    {testingZerodha ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                    Test Connection
                  </button>
                  {zerodhaTestResult && (
                    <span className={`text-sm ${zerodhaTestResult.success ? 'text-green-400' : 'text-red-400'}`}>
                      {zerodhaTestResult.success ? '✓ ' + zerodhaTestResult.message : '✗ ' + zerodhaTestResult.error}
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-500 mt-2">
                  Note: Paper trading uses MockKite. Real trading requires Zerodha credentials.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* View Navigation Tabs - Mobile responsive with horizontal scroll */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-2 mb-4 md:mb-6">
        <div className="overflow-x-auto scrollbar-hide">
          <div className="flex items-center gap-1 md:gap-2 bg-slate-800/50 rounded-lg p-1 min-w-max">
            <button
              onClick={() => setActiveView('dashboard')}
              className={`flex items-center gap-1 md:gap-2 px-2 md:px-4 py-1.5 md:py-2 rounded-lg transition text-xs md:text-sm whitespace-nowrap ${
                activeView === 'dashboard' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-slate-700'
              }`}
            >
              <LayoutGrid className="w-3 h-3 md:w-4 md:h-4" /> <span className="hidden sm:inline">Dashboard</span><span className="sm:hidden">Home</span>
            </button>
            <button
              onClick={() => setActiveView('heatmap')}
              className={`flex items-center gap-1 md:gap-2 px-2 md:px-4 py-1.5 md:py-2 rounded-lg transition text-xs md:text-sm whitespace-nowrap ${
                activeView === 'heatmap' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-slate-700'
              }`}
            >
              <Activity className="w-3 h-3 md:w-4 md:h-4" /> Heatmap
            </button>
            <button
              onClick={() => setActiveView('chart')}
              className={`flex items-center gap-1 md:gap-2 px-2 md:px-4 py-1.5 md:py-2 rounded-lg transition text-xs md:text-sm whitespace-nowrap ${
                activeView === 'chart' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-slate-700'
              }`}
            >
              <CandlestickChart className="w-3 h-3 md:w-4 md:h-4" /> Chart
            </button>
            <button
              onClick={() => setActiveView('autopsy')}
              className={`flex items-center gap-1 md:gap-2 px-2 md:px-4 py-1.5 md:py-2 rounded-lg transition text-xs md:text-sm whitespace-nowrap ${
                activeView === 'autopsy' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-slate-700'
              }`}
            >
              <FileText className="w-3 h-3 md:w-4 md:h-4" /> <span className="hidden md:inline">Daily Report</span><span className="md:hidden">Report</span>
            </button>
          </div>
        </div>
        
        {/* Trading Phase Badge - Responsive */}
        {tradingPhase && (
          <div className={`self-start sm:self-auto sm:ml-2 px-2 md:px-3 py-1 rounded-full text-[10px] md:text-xs font-medium ${
            tradingPhase.phase === 'ACTIVE' ? 'bg-green-500/20 text-green-400' :
            tradingPhase.phase === 'OBSERVATION' ? 'bg-yellow-500/20 text-yellow-400' :
            tradingPhase.phase === 'SQUAREOFF' ? 'bg-red-500/20 text-red-400' :
            'bg-gray-500/20 text-gray-400'
          }`}>
            {tradingPhase.phase_name || tradingPhase.phase}
            {tradingPhase.phase_remaining && <span className="ml-1 opacity-75">({tradingPhase.phase_remaining})</span>}
          </div>
        )}
      </div>

      {/* Views with CSS display for chart persistence */}
      <div style={{ display: activeView === 'heatmap' ? 'block' : 'none' }}>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-6">
          <div className="lg:col-span-2 order-1">
            <TechnicalHeatmap 
              onSelectTicker={(ticker) => {
                setSelectedTicker(ticker);
                setActiveView('chart');
              }}
              activeTicker={selectedTicker}
            />
          </div>
          <div className="order-2">
            <AIReasoningPanel ticker={selectedTicker} />
          </div>
        </div>
      </div>

      {/* Chart view - always mounted, hidden via CSS to preserve state */}
      <div style={{ display: activeView === 'chart' ? 'block' : 'none' }}>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-6">
          <div className="lg:col-span-2 order-1">
            <TradingChart
              ticker={selectedTicker}
              candles={chartData.candles || []}
              indicators={chartData.indicators || {}}
              position={positions.find(p => p.ticker === selectedTicker)}
              trades={trades.filter(t => t.ticker === selectedTicker)}
              height={typeof window !== 'undefined' && window.innerWidth < 768 ? 350 : 500}
            />
          </div>
          <div className="space-y-3 md:space-y-4 order-2">
            <AIReasoningPanel ticker={selectedTicker} />
            
            {/* Ticker Selector - Mobile optimized */}
            <div className="bg-slate-800 rounded-lg p-3 md:p-4 border border-slate-700">
              <h4 className="text-xs md:text-sm font-medium text-slate-400 mb-2 md:mb-3">Select Ticker</h4>
              <div className="flex flex-wrap gap-1.5 md:gap-2 max-h-32 overflow-y-auto">
                {status?.watchlist?.map(ticker => (
                  <button
                    key={ticker}
                    onClick={() => setSelectedTicker(ticker)}
                    className={`px-2 md:px-3 py-1 rounded-lg text-xs md:text-sm transition ${
                      selectedTicker === ticker 
                        ? 'bg-blue-600 text-white' 
                        : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                    }`}
                  >
                    {ticker}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div style={{ display: activeView === 'autopsy' ? 'block' : 'none' }}>
        <DailyAutopsy isVisible={activeView === 'autopsy'} />
      </div>

      <div style={{ display: activeView === 'dashboard' ? 'block' : 'none' }}>
          {/* Portfolio Overview - Mobile Responsive */}
          <div className="bg-gradient-to-r from-blue-900/50 to-purple-900/50 rounded-xl p-3 md:p-4 mb-4 md:mb-6 border border-blue-500/30">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
              <div className="flex items-center gap-2 md:gap-4 col-span-2 md:col-span-1">
                <Wallet className="w-6 h-6 md:w-8 md:h-8 text-blue-400 flex-shrink-0" />
                <div className="min-w-0">
                  <p className="text-gray-400 text-xs md:text-sm">Portfolio Value</p>
                  <p className="text-lg md:text-2xl font-bold truncate">₹{(status?.portfolio?.total_value || 100000).toLocaleString('en-IN', { minimumFractionDigits: 0 })}</p>
                </div>
              </div>
              <div className="text-right md:text-right">
                <p className="text-gray-400 text-xs md:text-sm">Available</p>
                <p className="text-base md:text-xl font-mono text-green-400 truncate">₹{(status?.portfolio?.available_cash || 100000).toLocaleString('en-IN', { minimumFractionDigits: 0 })}</p>
              </div>
              <div className="text-left md:text-right">
                <p className="text-gray-400 text-xs md:text-sm">Holdings</p>
                <p className="text-base md:text-xl font-mono truncate">₹{(status?.portfolio?.holdings_value || 0).toLocaleString('en-IN', { minimumFractionDigits: 0 })}</p>
              </div>
              <div className={`text-right px-2 md:px-4 py-1 md:py-2 rounded-lg ${(status?.portfolio?.total_pnl || 0) >= 0 ? 'bg-green-500/20' : 'bg-red-500/20'}`}>
                <p className="text-gray-400 text-xs md:text-sm">Total P&L</p>
                <p className={`text-base md:text-xl font-mono ${(status?.portfolio?.total_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {(status?.portfolio?.total_pnl || 0) >= 0 ? '+' : ''}₹{(status?.portfolio?.total_pnl || 0).toLocaleString('en-IN', { minimumFractionDigits: 0 })}
                  <span className="text-[10px] md:text-sm ml-1 block md:inline">({(status?.portfolio?.total_pnl_percent || 0).toFixed(1)}%)</span>
                </p>
              </div>
            </div>
          </div>

          {/* Stats Cards - Mobile Responsive */}
          <div className="grid grid-cols-2 md:grid-cols-2 lg:grid-cols-4 gap-2 md:gap-4 mb-4 md:mb-8">
        <StatCard
          title="Realized P&L"
          value={`₹${(status?.portfolio?.realized_pnl || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`}
          icon={<DollarSign className="w-5 h-5" />}
          trend={(status?.portfolio?.realized_pnl || 0) >= 0 ? 'up' : 'down'}
        />
        <StatCard
          title="Trades Today"
          value={status?.stats?.trades_executed || 0}
          icon={<Activity className="w-5 h-5" />}
          subtitle={`${status?.stats?.win_rate?.toFixed(1) || 0}% win rate`}
        />
        <StatCard
          title="Open Positions"
          value={positions.length}
          icon={<BarChart3 className="w-5 h-5" />}
          subtitle={`Unrealized: ₹${(status?.stats?.unrealized_pnl || 0).toFixed(2)}`}
        />
        <StatCard
          title="Risk Status"
          value={status?.risk?.kill_switch_triggered ? 'STOPPED' : 'ACTIVE'}
          icon={<AlertTriangle className="w-5 h-5" />}
          trend={status?.risk?.kill_switch_triggered ? 'down' : 'up'}
          subtitle={`MTM: ₹${Math.abs(status?.risk?.mtm_loss || 0).toFixed(2)}`}
        />
      </div>

      {/* Risk Bar - Mobile Responsive */}
      <div className="bg-sentinel-card rounded-xl p-3 md:p-4 mb-4 md:mb-8 border border-sentinel-border">
        <div className="flex items-center justify-between mb-2">
          <span className="text-gray-400 text-xs md:text-sm">Risk Utilization</span>
          <span className="text-xs md:text-sm">
            ₹{Math.abs(status?.risk?.mtm_loss || 0).toFixed(0)} / ₹{status?.risk?.limit?.toLocaleString()}
          </span>
        </div>
        <div className="h-2 md:h-3 bg-gray-700 rounded-full overflow-hidden">
          <div 
            className={`h-full transition-all duration-500 ${
              riskPercent > 80 ? 'bg-red-500' : riskPercent > 50 ? 'bg-yellow-500' : 'bg-green-500'
            }`}
            style={{ width: `${Math.min(riskPercent, 100)}%` }}
          />
        </div>
      </div>

      {/* Main Grid - Mobile Responsive */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-6">
        {/* Watchlist */}
        <div className="bg-sentinel-card rounded-xl border border-sentinel-border order-2 lg:order-1">
          <div className="p-3 md:p-4 border-b border-sentinel-border">
            <h2 className="font-semibold flex items-center gap-2 text-sm md:text-base">
              <TrendingUp className="w-4 h-4 md:w-5 md:h-5 text-blue-400" />
              Watchlist
            </h2>
          </div>
          <div className="p-2 md:p-4 space-y-1 md:space-y-2 max-h-64 md:max-h-none overflow-y-auto">
            {status?.watchlist?.map(ticker => (
              <WatchlistItem
                key={ticker}
                ticker={ticker}
                price={status?.prices?.[ticker] || 0}
                selected={selectedTicker === ticker}
                onClick={() => setSelectedTicker(ticker)}
                hasPosition={positions.some(p => p.ticker === ticker)}
                signal={signals[ticker]}
              />
            ))}
          </div>
        </div>

        {/* Selected Ticker Details */}
        <div className="lg:col-span-2 space-y-4 md:space-y-6 order-1 lg:order-2">
          {/* Ticker Info - Mobile Responsive */}
          <div className="bg-sentinel-card rounded-xl border border-sentinel-border p-3 md:p-4">
            <div className="flex items-center justify-between mb-3 md:mb-4">
              <div>
                <h2 className="text-lg md:text-xl font-bold">{selectedTicker}</h2>
                <p className="text-2xl md:text-3xl font-mono text-blue-400">
                  ₹{(status?.prices?.[selectedTicker] || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </p>
              </div>
              <div className="flex gap-1 md:gap-2">
                <button
                  onClick={() => executeTrade(selectedTicker, 'BUY')}
                  disabled={!status?.running}
                  className="px-3 md:px-4 py-1.5 md:py-2 text-sm bg-green-600 hover:bg-green-700 disabled:opacity-50 rounded-lg transition"
                >
                  Buy
                </button>
                <button
                  onClick={() => closePosition(selectedTicker)}
                  disabled={!positions.some(p => p.ticker === selectedTicker)}
                  className="px-3 md:px-4 py-1.5 md:py-2 text-sm bg-red-600 hover:bg-red-700 disabled:opacity-50 rounded-lg transition"
                >
                  Close
                </button>
              </div>
            </div>

            {/* Indicators */}
            {signals[selectedTicker]?.indicators && (
              <div className="grid grid-cols-4 gap-4">
                <IndicatorBox 
                  label="Price" 
                  value={signals[selectedTicker].indicators.price?.toFixed(2)} 
                />
                <IndicatorBox 
                  label="VWAP" 
                  value={signals[selectedTicker].indicators.vwap?.toFixed(2)}
                  highlight={signals[selectedTicker].indicators.price > signals[selectedTicker].indicators.vwap}
                />
                <IndicatorBox 
                  label="RSI(14)" 
                  value={signals[selectedTicker].indicators.rsi?.toFixed(1)}
                  highlight={signals[selectedTicker].indicators.rsi > 60}
                />
                <IndicatorBox 
                  label="EMA(20)" 
                  value={signals[selectedTicker].indicators.ema20?.toFixed(2)}
                  highlight={signals[selectedTicker].indicators.price > signals[selectedTicker].indicators.ema20}
                />
              </div>
            )}

            {/* Signal Status */}
            {signals[selectedTicker] && (
              <div className={`mt-4 p-3 rounded-lg ${signals[selectedTicker].has_signal ? 'bg-green-500/20 border border-green-500/50' : 'bg-gray-700/50'}`}>
                <div className="flex items-center gap-2">
                  {signals[selectedTicker].has_signal ? (
                    <CheckCircle className="w-5 h-5 text-green-400" />
                  ) : (
                    <XCircle className="w-5 h-5 text-gray-400" />
                  )}
                  <span className={signals[selectedTicker].has_signal ? 'text-green-400' : 'text-gray-400'}>
                    {signals[selectedTicker].has_signal ? 'Signal Active' : 'No Signal'}
                  </span>
                </div>
                {signals[selectedTicker].analysis?.reason && (
                  <p className="text-sm text-gray-400 mt-1">{signals[selectedTicker].analysis.reason}</p>
                )}
              </div>
            )}

            {/* News Panel */}
            <NewsPanel ticker={selectedTicker} apiBase={API_BASE} />
          </div>

          {/* Positions */}
          <div className="bg-sentinel-card rounded-xl border border-sentinel-border">
            <div className="p-4 border-b border-sentinel-border">
              <h2 className="font-semibold">Open Positions</h2>
            </div>
            <div className="p-4">
              {positions.length === 0 ? (
                <p className="text-gray-500 text-center py-4">No open positions</p>
              ) : (
                <div className="space-y-2">
                  {positions.map((pos, i) => (
                    <PositionRow key={i} position={pos} onClose={() => closePosition(pos.ticker)} />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Recent Trades */}
          <div className="bg-sentinel-card rounded-xl border border-sentinel-border">
            <div className="p-4 border-b border-sentinel-border flex items-center justify-between">
              <h2 className="font-semibold">Recent Trades</h2>
              <button onClick={fetchData} className="text-gray-400 hover:text-white">
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>
            <div className="p-4 max-h-64 overflow-y-auto">
              {trades.length === 0 ? (
                <p className="text-gray-500 text-center py-4">No trades today</p>
              ) : (
                <div className="space-y-2">
                  {trades.map((trade, i) => (
                    <TradeRow key={i} trade={trade} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
      </div>

      {/* Footer */}
      <footer className="mt-8 text-center text-gray-500 text-sm">
        <p>The Sentinel v2.0 | Market Hours: 9:15 AM - 3:30 PM IST</p>
        <p className="mt-1">
          <Clock className="w-4 h-4 inline mr-1" />
          {status?.risk?.market_open ? 'Market Open' : 'Market Closed'}
        </p>
      </footer>
    </div>
  );
}

// Component: Stat Card
function StatCard({ title, value, icon, trend, subtitle }) {
  return (
    <div className="bg-sentinel-card rounded-xl p-4 border border-sentinel-border">
      <div className="flex items-center justify-between mb-2">
        <span className="text-gray-400 text-sm">{title}</span>
        <span className={trend === 'up' ? 'text-green-400' : trend === 'down' ? 'text-red-400' : 'text-blue-400'}>
          {icon}
        </span>
      </div>
      <p className={`text-2xl font-bold ${trend === 'up' ? 'text-green-400' : trend === 'down' ? 'text-red-400' : ''}`}>
        {value}
      </p>
      {subtitle && <p className="text-gray-500 text-sm mt-1">{subtitle}</p>}
    </div>
  );
}

// Component: Watchlist Item
function WatchlistItem({ ticker, price, selected, onClick, hasPosition, signal }) {
  return (
    <div 
      onClick={onClick}
      className={`flex items-center justify-between p-3 rounded-lg cursor-pointer transition ${
        selected ? 'bg-blue-500/20 border border-blue-500/50' : 'hover:bg-gray-700/50'
      }`}
    >
      <div className="flex items-center gap-3">
        {hasPosition && <div className="w-2 h-2 bg-green-500 rounded-full" />}
        <span className="font-medium">{ticker}</span>
        {signal?.has_signal && (
          <span className="text-xs bg-green-500/20 text-green-400 px-2 py-0.5 rounded">SIGNAL</span>
        )}
      </div>
      <span className="font-mono">₹{price.toFixed(2)}</span>
    </div>
  );
}

// Component: Indicator Box
function IndicatorBox({ label, value, highlight }) {
  return (
    <div className={`p-3 rounded-lg ${highlight ? 'bg-green-500/20' : 'bg-gray-700/50'}`}>
      <p className="text-gray-400 text-xs">{label}</p>
      <p className={`font-mono text-lg ${highlight ? 'text-green-400' : ''}`}>{value || '-'}</p>
    </div>
  );
}

// Component: Position Row
function PositionRow({ position, onClose }) {
  const pnl = position.unrealized_pnl || 0;
  const isProfit = pnl >= 0;
  
  return (
    <div className="flex items-center justify-between p-3 bg-gray-700/30 rounded-lg">
      <div>
        <span className="font-medium">{position.ticker}</span>
        <span className="text-gray-400 text-sm ml-2">
          {position.quantity} @ ₹{position.entry_price?.toFixed(2)}
        </span>
      </div>
      <div className="flex items-center gap-4">
        <span className={`font-mono ${isProfit ? 'text-green-400' : 'text-red-400'}`}>
          {isProfit ? '+' : ''}₹{pnl.toFixed(2)}
        </span>
        <button onClick={onClose} className="text-red-400 hover:text-red-300">
          <XCircle className="w-5 h-5" />
        </button>
      </div>
    </div>
  );
}

// Component: Trade Row
function TradeRow({ trade }) {
  const pnl = trade.pnl || 0;
  const isProfit = pnl >= 0;
  
  return (
    <div className="flex items-center justify-between p-3 bg-gray-700/30 rounded-lg text-sm">
      <div className="flex items-center gap-3">
        <span className={`px-2 py-0.5 rounded text-xs ${trade.side === 'BUY' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
          {trade.side}
        </span>
        <span className="font-medium">{trade.ticker}</span>
      </div>
      <div className="text-right">
        <span className={`font-mono ${isProfit ? 'text-green-400' : 'text-red-400'}`}>
          {isProfit ? '+' : ''}₹{pnl.toFixed(2)}
        </span>
        <p className="text-gray-500 text-xs">{trade.reason}</p>
      </div>
    </div>
  );
}

// Component: News Panel
function NewsPanel({ ticker, apiBase }) {
  const [news, setNews] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [sourceType, setSourceType] = React.useState('');
  const [toggling, setToggling] = React.useState(false);

  const toggleSource = async () => {
    setToggling(true);
    try {
      await fetch(`${apiBase}/news/toggle-source`, { method: 'POST' });
      await fetchNews(true);
    } catch (err) {
      console.error('Error toggling news source:', err);
    }
    setToggling(false);
  };

  const fetchNews = React.useCallback(async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      const url = refresh 
        ? `${apiBase}/news/${ticker}/refresh`
        : `${apiBase}/news/${ticker}?limit=10`;
      const res = await fetch(url, { method: refresh ? 'POST' : 'GET' });
      const data = await res.json();
      setNews(data.news || []);
      setSourceType(data.source_type || 'unknown');
      if (data.error) setError(data.error);
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  }, [ticker, apiBase]);

  React.useEffect(() => {
    fetchNews(false);
    // Auto-refresh news every 2 minutes
    const interval = setInterval(() => fetchNews(true), 120000);
    return () => clearInterval(interval);
  }, [ticker, fetchNews]);

  const formatTime = (timestamp) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return date.toLocaleDateString();
  };

  return (
    <div className="bg-sentinel-card rounded-xl border border-sentinel-border mt-4">
      <div className="p-4 border-b border-sentinel-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Newspaper className="w-4 h-4 text-blue-400" />
          <h2 className="font-semibold">News for {ticker}</h2>
          <button
            onClick={toggleSource}
            disabled={toggling}
            className={`text-xs px-2 py-0.5 rounded cursor-pointer hover:opacity-80 ${sourceType === 'real' ? 'bg-green-500/20 text-green-400' : 'bg-yellow-500/20 text-yellow-400'}`}
            title="Click to toggle news source"
          >
            {toggling ? '...' : (sourceType === 'real' ? 'Live RSS' : 'Mock')}
          </button>
        </div>
        <button 
          onClick={() => fetchNews(true)}
          disabled={loading}
          className="flex items-center gap-1 text-gray-400 hover:text-white disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          <span className="text-sm">Refresh</span>
        </button>
      </div>
      <div className="p-4 max-h-72 overflow-y-auto">
        {loading && news.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 animate-spin text-blue-400" />
          </div>
        ) : error ? (
          <div className="text-center py-4">
            <p className="text-red-400 text-sm">{error}</p>
            <button onClick={() => fetchNews(true)} className="text-blue-400 text-sm mt-2 hover:underline">
              Try again
            </button>
          </div>
        ) : news.length === 0 ? (
          <p className="text-gray-500 text-center py-4">No news found for {ticker}</p>
        ) : (
          <div className="space-y-3">
            {news.map((item, i) => (
              <div key={i} className="p-3 bg-gray-700/30 rounded-lg hover:bg-gray-700/50 transition">
                <a 
                  href={item.link} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="text-sm font-medium hover:text-blue-400 transition"
                >
                  {item.headline}
                </a>
                <div className="flex items-center gap-2 mt-1.5 text-xs text-gray-500">
                  <span className="bg-gray-600/50 px-2 py-0.5 rounded">{item.source}</span>
                  <span>{formatTime(item.timestamp)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
