"use client";
import { createContext, useContext, useEffect, useState } from "react";

import { api, setAuthenticatedSessionKnown } from "./api";
import type { User } from "./types";

interface AuthCtx {
  user: User | null;
  loading: boolean;
  setSession: (user: User) => void;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthCtx>({
  user: null,
  loading: true,
  setSession: () => {},
  logout: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .me()
      .then((currentUser) => {
        setAuthenticatedSessionKnown(true);
        setUser(currentUser);
      })
      .catch(() => {
        setAuthenticatedSessionKnown(false);
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  function setSession(u: User) {
    setAuthenticatedSessionKnown(true);
    setUser(u);
  }

  async function logout() {
    try {
      await api.logout();
    } catch {
      // The account may already be deleted or the session may have expired.
    } finally {
      setAuthenticatedSessionKnown(false);
      setUser(null);
    }
  }

  return <Ctx.Provider value={{ user, loading, setSession, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
