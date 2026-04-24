import React, { createContext, useContext, useState, useEffect } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

type User = { id: string; email: string; name: string } | null;
type AuthCtx = { user: User; token: string | null; loading: boolean; login: (email: string, password: string) => Promise<string | null>; logout: () => void };

const AuthContext = createContext<AuthCtx>({ user: null, token: null, loading: true, login: async () => null, logout: () => {} });

export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const savedToken = await AsyncStorage.getItem('auth_token');
        if (savedToken) {
          const r = await fetch(`${BACKEND_URL}/api/auth/me`, { headers: { Authorization: `Bearer ${savedToken}` } });
          if (r.ok) {
            const userData = await r.json();
            setUser(userData);
            setToken(savedToken);
          } else {
            await AsyncStorage.removeItem('auth_token');
          }
        }
      } catch (e) { console.error('Auth check failed:', e); }
      finally { setLoading(false); }
    })();
  }, []);

  const login = async (email: string, password: string): Promise<string | null> => {
    try {
      const r = await fetch(`${BACKEND_URL}/api/auth/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
      });
      if (!r.ok) {
        const err = await r.json();
        return typeof err.detail === 'string' ? err.detail : 'Login failed';
      }
      const data = await r.json();
      await AsyncStorage.setItem('auth_token', data.token);
      setToken(data.token);
      setUser(data.user);
      return null;
    } catch (e) { return 'Network error. Please try again.'; }
  };

  const logout = async () => {
    await AsyncStorage.removeItem('auth_token');
    setToken(null);
    setUser(null);
  };

  return <AuthContext.Provider value={{ user, token, loading, login, logout }}>{children}</AuthContext.Provider>;
}
