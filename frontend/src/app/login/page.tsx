"use client";

import { FormEvent, useEffect, useState } from "react";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [setupError, setSetupError] = useState("");
  const [setupMessage, setSetupMessage] = useState("");

  useEffect(() => {
    fetch("/api/access/login", { credentials: "include" })
      .then((response) => response.json())
      .then((data) => {
        if (data?.configured === false) {
          const missing = Array.isArray(data.missing) && data.missing.length ? ` Missing: ${data.missing.join(", ")}.` : "";
          setSetupError(`${data.message ?? "Performance OS access is not configured."}${missing}`);
        } else if (data?.message) {
          setSetupMessage(data.message);
        }
      })
      .catch(() => undefined);
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (setupError) return;
    setLoading(true);
    setError("");
    const response = await fetch("/api/access/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    setLoading(false);

    if (!response.ok) {
      const data = await response.json().catch(() => null);
      setError(data?.message ?? "Invalid password.");
      return;
    }

    const params = new URLSearchParams(window.location.search);
    const nextPath = params.get("next");
    window.location.href = nextPath?.startsWith("/") && !nextPath.startsWith("//") ? nextPath : "/";
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#07080b] p-6 text-zinc-100">
      <form onSubmit={submit} className="w-full max-w-sm rounded-xl border border-white/10 bg-zinc-950/80 p-6 shadow-2xl shadow-black/30">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300/80">Private Access</p>
        <h1 className="mt-2 text-2xl font-semibold text-white">Performance OS</h1>
        <p className="mt-2 text-sm leading-6 text-zinc-400">Enter your access password to open your private dashboard.</p>
        {setupMessage && !setupError ? <p className="mt-4 rounded-lg border border-emerald-300/20 bg-emerald-300/10 p-3 text-sm text-emerald-100">{setupMessage}</p> : null}
        {setupError ? <p className="mt-4 rounded-lg border border-amber-300/30 bg-amber-300/10 p-3 text-sm text-amber-100">{setupError}</p> : null}
        <label className="mt-6 block space-y-2 text-sm text-zinc-400">
          <span>Password</span>
          <input
            className="h-11 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 text-zinc-100 outline-none transition placeholder:text-zinc-600 focus:border-cyan-300/60"
            value={password}
            type="password"
            autoFocus
            disabled={Boolean(setupError)}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error ? <p className="mt-3 rounded-lg border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-100">{error}</p> : null}
        <button className="mt-5 h-11 w-full rounded-lg bg-cyan-300 text-sm font-semibold text-zinc-950 disabled:cursor-not-allowed disabled:opacity-60" disabled={loading || Boolean(setupError)}>
          {loading ? "Unlocking..." : "Unlock"}
        </button>
      </form>
    </main>
  );
}
