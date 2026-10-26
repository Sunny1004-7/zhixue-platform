import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useApi } from "../RuntimeContext";
import type { Role, User } from "../types";
type Session = {
  user: User | null;
  loading: boolean;
  login: (account: string, password: string, role: Role) => Promise<User>;
  logout: () => Promise<void>;
};
const Context = createContext<Session | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    if (!api.hasToken()) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then((u) => {
        if (active) setUser(u);
      })
      .catch(() => {
        api.clearToken();
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api]);
  const login = useCallback(
    async (account: string, password: string, role: Role) => {
      const result = await api.login(account, password, role);
      setUser(result.user);
      sessionStorage.removeItem("zhixue-exit-message");
      return result.user;
    },
    [api],
  );
  const logout = useCallback(async () => {
    // Local identity must be removed even if server revocation cannot be confirmed.
    let confirmed = false;
    try {
      await api.logout();
      confirmed = true;
    } catch {
      /* The login page explains that server revocation is unconfirmed. */
    } finally {
      api.clearToken();
      for (const key of Object.keys(sessionStorage)) {
        if (
          /^(zhixing-course|zhixing-practice|zhixue-draft|zhixue-session)/.test(
            key,
          )
        )
          sessionStorage.removeItem(key);
      }
      sessionStorage.setItem(
        "zhixue-exit-message",
        confirmed
          ? "已退出当前账号。"
          : "已退出本机账号。网络未连接，暂时无法确认服务器会话已撤销。",
      );
      window.dispatchEvent(new Event("zhixue-session-cleared"));
      setUser(null);
    }
  }, [api]);
  const value = useMemo(
    () => ({ user, loading, login, logout }),
    [user, loading, login, logout],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useAuth() {
  const value = useContext(Context);
  if (!value) throw new Error("Missing session provider");
  return value;
}
