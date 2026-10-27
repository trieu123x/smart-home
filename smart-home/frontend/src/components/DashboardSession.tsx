"use client";

import { createContext, useContext, useEffect, useState, type FormEvent } from "react";
import { api, AUTH_EXPIRED } from "@/lib/api";

const SessionContext = createContext<{ logout: () => void }>({ logout: () => {} });
export const useSession = () => useContext(SessionContext);

export function DashboardSession({ children }: { children: React.ReactNode }) {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [configured, setConfigured] = useState(true);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    api.session().then((value) => {
      if (active) { setAuthenticated(value.authenticated); setConfigured(value.configured); }
    }).catch(() => { if (active) { setAuthenticated(false); setError("Không kết nối được máy chủ."); } });
    const expired = () => setAuthenticated(false);
    window.addEventListener(AUTH_EXPIRED, expired);
    return () => { active = false; window.removeEventListener(AUTH_EXPIRED, expired); };
  }, []);

  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { await api.login(password); setPassword(""); setAuthenticated(true); }
    catch (err) { setError(err instanceof Error ? err.message : "Chưa đăng nhập được."); }
    finally { setBusy(false); }
  }
  async function logout() {
    try { await api.logout(); setAuthenticated(false); }
    catch (err) { window.alert(err instanceof Error ? err.message : "Chưa đăng xuất được."); }
  }
  if (authenticated === null) return <main className="grid min-h-screen place-items-center text-slate-400">Đang kết nối dashboard…</main>;
  if (!authenticated) return (
    <main className="grid min-h-screen place-items-center p-6">
      <form onSubmit={login} className="card w-full max-w-sm space-y-4">
        <h1 className="text-xl font-semibold">Smart Home</h1>
        <p className="text-sm text-slate-400">Đăng nhập để quản lý thiết bị, camera và cảnh báo.</p>
        {!configured && <p role="alert" className="text-sm text-amber-300">Chưa thiết lập mật khẩu dashboard trên máy chủ.</p>}
        <label className="block text-sm">Mật khẩu
          <input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-ink-950 px-3 py-2 text-white" />
        </label>
        {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
        <button type="submit" className="btn w-full" disabled={busy}>{busy ? "Đang đăng nhập…" : "Đăng nhập"}</button>
      </form>
    </main>
  );
  return <SessionContext.Provider value={{ logout: () => void logout() }}>{children}</SessionContext.Provider>;
}
