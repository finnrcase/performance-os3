"use client";

import { FormEvent, useState } from "react";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    const response = await fetch("/api/access/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    setLoading(false);

    if (!response.ok) {
      setError("Invalid password.");
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
        <label className="mt-6 block space-y-2 text-sm text-zinc-400">
          <span>Password</span>
          <input
            className="h-11 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 text-zinc-100 outline-none transition placeholder:text-zinc-600 focus:border-cyan-300/60"
            value={password}
            type="password"
            autoFocus
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error ? <p className="mt-3 rounded-lg border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-100">{error}</p> : null}
        <button className="mt-5 h-11 w-full rounded-lg bg-cyan-300 text-sm font-semibold text-zinc-950 disabled:opacity-60" disabled={loading}>
          {loading ? "Unlocking..." : "Unlock"}
        </button>
      </form>
    </main>
  );
}
