import React, { useEffect, useState, useCallback } from 'react';
import {
  AreaChart, Area, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts';
import { TrendingUp, TrendingDown, RefreshCw, BarChart2 } from 'lucide-react';

const API_BASE = '/api';

const fmt = (n) =>
  n == null ? '—' : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n);

const pctFmt = (n) => (n == null ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`);

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 text-xs shadow-xl">
      <div className="text-slate-400 mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ color: p.color }} className="font-mono">
          {p.name}: {p.dataKey === 'equity' ? fmt(p.value) : pctFmt(p.value)}
        </div>
      ))}
    </div>
  );
};

export default function EquityCurve({ days = 30 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState('equity'); // 'equity' | 'daily' | 'drawdown'

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/pnl-history?days=${days}`);
      setData(await res.json());
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  // Compute drawdown series from equity data
  const drawdownSeries = React.useMemo(() => {
    if (!data?.equity?.length) return [];
    let peak = data.starting_capital ?? data.equity[0]?.equity ?? 100000;
    return data.equity.map(({ date, equity }) => {
      peak = Math.max(peak, equity);
      const dd = peak > 0 ? -((peak - equity) / peak) * 100 : 0;
      return { date, drawdown: parseFloat(dd.toFixed(2)) };
    });
  }, [data]);

  if (loading) {
    return (
      <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-400" />
      </div>
    );
  }

  if (!data || (!data.equity?.length && !data.daily?.length)) {
    return (
      <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 flex flex-col items-center justify-center h-64 text-slate-400 gap-3">
        <BarChart2 size={32} />
        <p className="text-sm">No trade history yet. Performance will appear here after the first closed trade.</p>
      </div>
    );
  }

  const totalPnl = data.total_pnl ?? 0;
  const isProfit = totalPnl >= 0;
  const startCap = data.starting_capital ?? 100000;
  const pnlPct = startCap > 0 ? (totalPnl / startCap) * 100 : 0;

  return (
    <div className="bg-slate-800 rounded-lg p-4 border border-slate-700 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart2 size={18} className="text-cyan-400" />
          <h3 className="text-white font-bold">Performance ({days}d)</h3>
        </div>
        <button
          onClick={load}
          className="text-slate-400 hover:text-white transition-colors"
          title="Refresh"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard
          label="Total P&L"
          value={fmt(totalPnl)}
          sub={pctFmt(pnlPct)}
          color={isProfit ? 'text-emerald-400' : 'text-red-400'}
          icon={isProfit ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
        />
        <StatCard
          label="Max Drawdown"
          value={`${data.max_drawdown?.toFixed(2) ?? '0.00'}%`}
          color="text-orange-400"
        />
        <StatCard
          label="Days Tracked"
          value={data.daily?.length ?? 0}
        />
        <StatCard
          label="Current Equity"
          value={fmt((data.equity?.at(-1)?.equity) ?? startCap)}
        />
      </div>

      {/* View switcher */}
      <div className="flex gap-2 text-xs">
        {[
          { key: 'equity', label: 'Equity Curve' },
          { key: 'daily', label: 'Daily P&L' },
          { key: 'drawdown', label: 'Drawdown' },
        ].map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setView(key)}
            className={`px-3 py-1 rounded-full transition-colors ${
              view === key
                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Chart */}
      <div className="h-52">
        <ResponsiveContainer width="100%" height="100%">
          {view === 'equity' ? (
            <AreaChart data={data.equity} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
              <defs>
                <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d2d44" />
              <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} axisLine={false}
                tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine y={startCap} stroke="#4361ee" strokeDasharray="4 2" />
              <Area type="monotone" dataKey="equity" name="Equity" stroke="#06b6d4"
                fill="url(#equityGrad)" strokeWidth={2} dot={false} />
            </AreaChart>
          ) : view === 'daily' ? (
            <LineChart data={data.daily} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d2d44" />
              <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} axisLine={false}
                tickFormatter={(v) => `₹${v}`} />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine y={0} stroke="#64748b" />
              <Line type="monotone" dataKey="pnl" name="Daily P&L" stroke="#f59e0b"
                strokeWidth={2} dot={{ r: 3, fill: '#f59e0b' }} />
            </LineChart>
          ) : (
            <AreaChart data={drawdownSeries} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
              <defs>
                <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d2d44" />
              <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} axisLine={false}
                tickFormatter={(v) => `${v}%`} domain={['auto', 0]} />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine y={0} stroke="#64748b" />
              <Area type="monotone" dataKey="drawdown" name="Drawdown" stroke="#ef4444"
                fill="url(#ddGrad)" strokeWidth={2} dot={false} />
            </AreaChart>
          )}
        </ResponsiveContainer>
      </div>

      {/* Daily table */}
      {data.daily?.length > 0 && (
        <div className="overflow-auto max-h-40">
          <table className="w-full text-xs text-slate-300">
            <thead>
              <tr className="text-slate-500 border-b border-slate-700">
                <th className="text-left py-1">Date</th>
                <th className="text-right py-1">P&L</th>
                <th className="text-right py-1">Trades</th>
                <th className="text-right py-1">Win%</th>
              </tr>
            </thead>
            <tbody>
              {[...data.daily].reverse().map((row) => (
                <tr key={row.date} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                  <td className="py-1">{row.date}</td>
                  <td className={`py-1 text-right font-mono ${row.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {row.pnl >= 0 ? '+' : ''}{fmt(row.pnl)}
                  </td>
                  <td className="py-1 text-right">{row.trades}</td>
                  <td className="py-1 text-right">{row.win_rate}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, sub, color = 'text-white', icon }) {
  return (
    <div className="bg-slate-900 rounded-lg p-3">
      <div className="text-slate-500 text-xs mb-1">{label}</div>
      <div className={`font-bold text-sm font-mono flex items-center gap-1 ${color}`}>
        {icon}{value}
      </div>
      {sub && <div className={`text-xs font-mono mt-0.5 ${color}`}>{sub}</div>}
    </div>
  );
}
