import { useAuth } from '../src/AuthContext';

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

export function useApi() {
  const { token } = useAuth();

  const apiFetch = async (path: string, options: RequestInit = {}) => {
    const headers: any = { ...options.headers };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    if (options.body) headers['Content-Type'] = 'application/json';
    return fetch(`${BACKEND_URL}${path}`, { ...options, headers });
  };

  return { apiFetch };
}
