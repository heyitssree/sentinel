import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const DailyAutopsy = ({ isVisible = true }) => {
  const [markdown, setMarkdown] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [source, setSource] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  useEffect(() => {
    if (isVisible) {
      fetchAutopsy();
    }
  }, [isVisible]);

  const fetchAutopsy = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch('/api/autopsy/daily');
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const data = await response.json();
      setMarkdown(data.markdown || '');
      setSource(data.source);
      setLastUpdated(data.timestamp);
      
      if (data.error) {
        console.warn('Autopsy warning:', data.error);
      }
    } catch (err) {
      setError(err.message);
      console.error('Failed to fetch autopsy:', err);
    } finally {
      setLoading(false);
    }
  };

  const getSourceBadge = () => {
    switch (source) {
      case 'generated':
        return <span className="px-2 py-1 bg-green-500/20 text-green-400 text-xs rounded">AI Generated</span>;
      case 'cached':
        return <span className="px-2 py-1 bg-blue-500/20 text-blue-400 text-xs rounded">Cached</span>;
      case 'mock':
        return <span className="px-2 py-1 bg-yellow-500/20 text-yellow-400 text-xs rounded">Mock Data</span>;
      case 'error':
        return <span className="px-2 py-1 bg-red-500/20 text-red-400 text-xs rounded">Error - Using Fallback</span>;
      default:
        return null;
    }
  };

  if (!isVisible) return null;

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
      {/* Header */}
      <div className="flex justify-between items-center p-4 border-b border-slate-700 bg-slate-800/50">
        <h3 className="text-lg font-semibold text-white flex items-center gap-2">
          <span className="text-2xl">📋</span>
          Daily Autopsy Report
        </h3>
        
        <div className="flex items-center gap-3">
          {getSourceBadge()}
          
          <button
            onClick={fetchAutopsy}
            disabled={loading}
            className="p-2 bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors disabled:opacity-50"
            title="Refresh Report"
          >
            {loading ? (
              <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            ) : (
              <span>🔄</span>
            )}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="p-4">
        {loading && !markdown ? (
          <div className="flex items-center justify-center h-48">
            <div className="text-center">
              <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500 mx-auto mb-3"></div>
              <p className="text-slate-400">Generating report with Gemini AI...</p>
            </div>
          </div>
        ) : error && !markdown ? (
          <div className="text-center py-8">
            <div className="text-red-400 mb-3">❌ {error}</div>
            <button
              onClick={fetchAutopsy}
              className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm"
            >
              Retry
            </button>
          </div>
        ) : (
          <div className="autopsy-content prose prose-invert prose-sm max-w-none">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({ children }) => (
                  <h1 className="text-2xl font-bold text-white mb-4 pb-2 border-b border-slate-700">
                    {children}
                  </h1>
                ),
                h2: ({ children }) => (
                  <h2 className="text-xl font-semibold text-white mt-6 mb-3 flex items-center gap-2">
                    {children}
                  </h2>
                ),
                h3: ({ children }) => (
                  <h3 className="text-lg font-medium text-slate-200 mt-4 mb-2">
                    {children}
                  </h3>
                ),
                p: ({ children }) => (
                  <p className="text-slate-300 mb-3 leading-relaxed">{children}</p>
                ),
                strong: ({ children }) => (
                  <strong className="text-white font-semibold">{children}</strong>
                ),
                em: ({ children }) => (
                  <em className="text-slate-400 italic">{children}</em>
                ),
                ul: ({ children }) => (
                  <ul className="list-disc list-inside space-y-1 text-slate-300 mb-4">{children}</ul>
                ),
                ol: ({ children }) => (
                  <ol className="list-decimal list-inside space-y-1 text-slate-300 mb-4">{children}</ol>
                ),
                li: ({ children }) => (
                  <li className="text-slate-300">{children}</li>
                ),
                blockquote: ({ children }) => (
                  <blockquote className="border-l-4 border-blue-500 pl-4 py-2 my-4 bg-slate-700/30 rounded-r italic text-slate-300">
                    {children}
                  </blockquote>
                ),
                hr: () => (
                  <hr className="border-slate-700 my-6" />
                ),
                table: ({ children }) => (
                  <div className="overflow-x-auto my-4">
                    <table className="min-w-full border border-slate-700 rounded-lg overflow-hidden">
                      {children}
                    </table>
                  </div>
                ),
                thead: ({ children }) => (
                  <thead className="bg-slate-700">{children}</thead>
                ),
                th: ({ children }) => (
                  <th className="px-4 py-2 text-left text-sm font-semibold text-white border-b border-slate-600">
                    {children}
                  </th>
                ),
                td: ({ children }) => (
                  <td className="px-4 py-2 text-sm text-slate-300 border-b border-slate-700">
                    {children}
                  </td>
                ),
                code: ({ inline, children }) =>
                  inline ? (
                    <code className="px-1.5 py-0.5 bg-slate-700 rounded text-cyan-400 text-sm font-mono">
                      {children}
                    </code>
                  ) : (
                    <pre className="bg-slate-900 rounded-lg p-4 overflow-x-auto my-4">
                      <code className="text-sm font-mono text-slate-300">{children}</code>
                    </pre>
                  ),
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:text-blue-300 underline"
                  >
                    {children}
                  </a>
                ),
              }}
            >
              {markdown}
            </ReactMarkdown>
          </div>
        )}
      </div>

      {/* Footer */}
      {lastUpdated && (
        <div className="px-4 py-2 border-t border-slate-700 text-xs text-slate-500 flex justify-between">
          <span>Source: {source}</span>
          <span>Updated: {new Date(lastUpdated).toLocaleString()}</span>
        </div>
      )}
    </div>
  );
};

export default DailyAutopsy;
