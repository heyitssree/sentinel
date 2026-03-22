import { useState, useCallback } from 'react';

const API_BASE = '/api';

/**
 * Manages API credential state: fetch status, save, and test
 * connections for Gemini and Zerodha.
 */
export function useCredentials() {
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
  const [zerodhaAuthResult, setZerodhaAuthResult] = useState(null);

  const fetchCredentials = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/credentials/status`);
      setCredentials(await res.json());
    } catch {
      // ignore
    }
  }, []);

  const testGemini = useCallback(async () => {
    setTestingGemini(true);
    setGeminiTestResult(null);
    try {
      const res = await fetch(`${API_BASE}/credentials/test/gemini`, { method: 'POST' });
      setGeminiTestResult(await res.json());
    } catch (e) {
      setGeminiTestResult({ success: false, error: e.message });
    }
    setTestingGemini(false);
  }, []);

  const testZerodha = useCallback(async () => {
    setTestingZerodha(true);
    setZerodhaTestResult(null);
    try {
      const res = await fetch(`${API_BASE}/credentials/test/zerodha`, { method: 'POST' });
      setZerodhaTestResult(await res.json());
    } catch (e) {
      setZerodhaTestResult({ success: false, error: e.message });
    }
    setTestingZerodha(false);
  }, []);

  const updateGeminiKey = useCallback(async (onSuccess) => {
    if (!geminiKey.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/credentials/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential_type: 'gemini', api_key: geminiKey }),
      });
      const data = await res.json();
      if (data.success) {
        setGeminiKey('');
        fetchCredentials();
        onSuccess?.('Gemini API key updated successfully');
      }
    } catch {
      // propagate via caller's toast
    }
  }, [geminiKey, fetchCredentials]);

  const updateZerodhaCredentials = useCallback(async (onSuccess) => {
    if (!zerodhaKey.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/credentials/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          credential_type: 'zerodha',
          api_key: zerodhaKey,
          api_secret: zerodhaSecret || undefined,
        }),
      });
      const data = await res.json();
      if (data.success) {
        setZerodhaKey('');
        setZerodhaSecret('');
        fetchCredentials();
        onSuccess?.('Zerodha credentials updated successfully');
      }
    } catch {
      // propagate via caller's toast
    }
  }, [zerodhaKey, zerodhaSecret, fetchCredentials]);

  const openZerodhaLogin = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/zerodha/login-url`);
      const data = await res.json();
      if (data.success && data.login_url) {
        window.open(data.login_url, '_blank', 'noopener,noreferrer');
        setZerodhaAuthResult(null);
      } else {
        setZerodhaAuthResult({ success: false, error: data.error || 'Could not generate login URL.' });
      }
    } catch (err) {
      setZerodhaAuthResult({ success: false, error: err.message });
    }
  }, []);

  return {
    credentials, fetchCredentials,
    geminiKey, setGeminiKey, showGeminiKey, setShowGeminiKey,
    zerodhaKey, setZerodhaKey, zerodhaSecret, setZerodhaSecret,
    showZerodhaKey, setShowZerodhaKey,
    testingGemini, testingZerodha,
    geminiTestResult, zerodhaTestResult,
    zerodhaAuthResult,
    testGemini, testZerodha,
    updateGeminiKey, updateZerodhaCredentials, openZerodhaLogin,
  };
}
