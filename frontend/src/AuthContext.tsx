import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from './api';
import type { Role, User } from './types';

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  login: (account: string, password: string, role: Role) => Promise<User>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    if (!api.hasToken()) {
      setLoading(false);
      return () => { active = false; };
    }
    api.me()
      .then((value) => { if (active) setUser(value); })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) api.clearToken();
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    loading,
    async login(account, password, role) {
      const result = await api.login(account, password, role);
      setUser(result.user);
      return result.user;
    },
    async logout() {
      await api.logout();
      setUser(null);
    },
  }), [user, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth 必须在 AuthProvider 中使用');
  return value;
}
