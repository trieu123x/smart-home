"use client";

import { Home, LogIn } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api, setToken } from "@/lib/api";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const { token } = await api.login(password);
      setToken(token);
      // Full reload so the dashboard provider starts fresh with the token
      window.location.href = "/";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không đăng nhập được");
      setSubmitting(false);
    }
  };

  return (
    <main className="grid min-h-screen place-items-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-5">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-500/15 text-brand-400">
            <Home size={20} />
          </span>
          <div>
            <h1 className="text-sm font-semibold text-white">Smart Home</h1>
            <p className="muted">Nhập mật khẩu để vào bảng điều khiển</p>
          </div>
        </div>

        <label className="block text-sm text-slate-300">
          Mật khẩu
          <input
            type="password"
            className="input mt-1"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            autoFocus
            required
          />
        </label>

        {error && (
          <p role="alert" className="text-sm text-rose-300">
            {error}
          </p>
        )}

        <button type="submit" className="btn-primary w-full justify-center" disabled={submitting}>
          <LogIn size={16} />
          Đăng nhập
        </button>
      </form>
    </main>
  );
}
