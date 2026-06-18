"use client";
import { createContext, useCallback, useContext, useRef, useState } from "react";

const Ctx = createContext<(msg: string) => void>(() => {});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flash = useCallback((m: string) => {
    setMsg(m);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setMsg(null), 2600);
  }, []);

  return (
    <Ctx.Provider value={flash}>
      {children}
      {msg && (
        <div
          style={{
            position: "fixed",
            bottom: 26,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 80,
            background: "#181613",
            color: "#faf8f3",
            padding: "13px 22px",
            borderRadius: 12,
            fontSize: 14.5,
            fontWeight: 500,
            boxShadow: "0 12px 34px rgba(0,0,0,.28)",
            display: "flex",
            alignItems: "center",
            gap: 10,
            animation: "pfrise .25s ease",
          }}
        >
          <span style={{ color: "#39ff88" }}>✓</span> {msg}
        </div>
      )}
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
