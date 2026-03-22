import { useState, useRef, useCallback } from 'react';

const BASE_DELAY = 1000;
const MAX_ATTEMPTS = 10;

/**
 * Manages a WebSocket connection to the Sentinel backend with
 * exponential backoff reconnection logic.
 *
 * @param {function} onMessage - called with the parsed JSON message object
 * @returns {{ wsConnected, connectWebSocket, disconnectWebSocket }}
 */
export function useWebSocket(onMessage) {
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const reconnectAttemptRef = useRef(0);

  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = window.location.host.includes(':5173')
      ? `${window.location.hostname}:8000`
      : window.location.host;

    const ws = new WebSocket(`${wsProtocol}//${wsHost}/ws`);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsConnected(true);
      reconnectAttemptRef.current = 0;
    };

    ws.onclose = (event) => {
      setWsConnected(false);
      wsRef.current = null;
      if (event.code === 1000 || reconnectAttemptRef.current >= MAX_ATTEMPTS) return;

      const delay = Math.min(BASE_DELAY * Math.pow(2, reconnectAttemptRef.current), 32000);
      reconnectAttemptRef.current++;
      reconnectTimeoutRef.current = setTimeout(connectWebSocket, delay);
    };

    ws.onerror = () => setWsConnected(false);

    ws.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        // ignore malformed messages
      }
    };
  }, [onMessage]);

  const disconnectWebSocket = useCallback(() => {
    if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    wsRef.current?.close(1000);
    wsRef.current = null;
  }, []);

  return { wsConnected, connectWebSocket, disconnectWebSocket };
}
