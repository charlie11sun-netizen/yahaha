"use client";
import { createContext, useContext, useEffect, useState } from "react";

import { api, ApiError } from "./api";
import type { User } from "./types";

interface AuthCtx {
  user: User | null;
  loading: boolean;
  setSession: (token: string, user: User) => void;
  logout: () => void;
}

const Ctx = createContext<AuthCtx>({
  user: null,
  loading: true,
  setSession: () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = localStorage.getItem("pf_token");
    if (!t) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch((err) => {
        // 只有 401/403（token 失效/账号禁用）才清 token；
        // 网络抖动或后端重启不应把用户静默登出。
        if (
          err instanceof ApiError &&
          (err.status === 401 || err.status === 403) &&
          !err.message.toLowerCase().includes("site locked")
        ) {
          localStorage.removeItem("pf_token");
        }
      })
      .finally(() => setLoading(false));
  }, []);

  function setSession(token: string, u: User) {
    localStorage.setItem("pf_token", token);
    setUser(u);
  }

  function logout() {
    api.logout().catch(() => {});
    localStorage.removeItem("pf_token");
    setUser(null);
  }

  return <Ctx.Provider value={{ user, loading, setSession, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
