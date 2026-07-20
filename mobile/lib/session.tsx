import * as SecureStore from 'expo-secure-store';
import { createContext, PropsWithChildren, useContext, useEffect, useMemo, useState } from 'react';

import { DEFAULT_API_URL, HeraclesApi } from './api';

const TOKEN_KEY = 'heracles.webToken';
const API_URL_KEY = 'heracles.apiUrl';

type SessionContextValue = {
  api: HeraclesApi | null;
  apiUrl: string;
  token: string;
  isReady: boolean;
  saveSettings: (next: { apiUrl: string; token: string }) => Promise<void>;
  clearToken: () => Promise<void>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: PropsWithChildren) {
  const [apiUrl, setApiUrl] = useState(DEFAULT_API_URL);
  const [token, setToken] = useState('');
  const [isReady, setReady] = useState(false);

  useEffect(() => {
    let mounted = true;
    async function load() {
      const [storedToken, storedApiUrl] = await Promise.all([
        SecureStore.getItemAsync(TOKEN_KEY),
        SecureStore.getItemAsync(API_URL_KEY),
      ]);
      if (!mounted) {
        return;
      }
      setToken(storedToken ?? '');
      setApiUrl(storedApiUrl || DEFAULT_API_URL);
      setReady(true);
    }
    load();
    return () => {
      mounted = false;
    };
  }, []);

  const api = useMemo(() => {
    if (!token.trim()) {
      return null;
    }
    return new HeraclesApi({ baseUrl: apiUrl, token: token.trim() });
  }, [apiUrl, token]);

  async function saveSettings(next: { apiUrl: string; token: string }) {
    const normalizedUrl = next.apiUrl.trim().replace(/\/$/, '') || DEFAULT_API_URL;
    const normalizedToken = next.token.trim();
    await Promise.all([
      SecureStore.setItemAsync(API_URL_KEY, normalizedUrl),
      SecureStore.setItemAsync(TOKEN_KEY, normalizedToken),
    ]);
    setApiUrl(normalizedUrl);
    setToken(normalizedToken);
  }

  async function clearToken() {
    await SecureStore.deleteItemAsync(TOKEN_KEY);
    setToken('');
  }

  return (
    <SessionContext.Provider value={{ api, apiUrl, token, isReady, saveSettings, clearToken }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error('useSession must be used inside SessionProvider');
  }
  return value;
}
