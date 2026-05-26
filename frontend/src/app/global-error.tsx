"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect, useMemo, useState } from "react";

function currentRoute() {
  if (typeof window === "undefined") return "";
  return `${window.location.pathname}${window.location.search}`;
}

export default function GlobalError({
  error,
}: Readonly<{
  error: Error & { digest?: string };
}>) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  const report = useMemo(
    () => JSON.stringify({
      title: "Global app crash",
      route: currentRoute(),
      timestamp: new Date().toISOString(),
      user_action: "global-render",
      error_message: error.message || "Unknown global error.",
      digest: error.digest ?? null,
      stack_trace: error.stack ?? null,
      state_summary: {
        app: "performance-os-frontend",
        fallback: "global-error",
      },
    }, null, 2),
    [error],
  );

  const copyReport = async () => {
    try {
      await navigator.clipboard.writeText(report);
      setCopied(true);
    } catch {
      window.prompt("Copy debug report", report);
    }
  };

  return (
    <html lang="en">
      <body style={{ margin: 0, background: "#07080b", color: "#f4f4f5", fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}>
        <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: "24px" }}>
          <section style={{ width: "min(100%, 640px)", border: "1px solid rgba(251, 191, 36, 0.28)", borderRadius: "18px", background: "rgba(251, 191, 36, 0.08)", padding: "24px", boxShadow: "0 24px 80px rgba(0, 0, 0, 0.35)" }}>
            <p style={{ margin: "0 0 8px", color: "rgba(253, 230, 138, 0.75)", fontSize: "12px", fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}>Performance OS</p>
            <h1 style={{ margin: 0, fontSize: "24px", lineHeight: 1.2 }}>The app hit a recoverable crash.</h1>
            <p style={{ margin: "12px 0 0", color: "rgba(254, 243, 199, 0.8)", fontSize: "14px", lineHeight: 1.6 }}>
              Reload to try again. If it keeps happening, copy the debug report so the failing route and stack trace are preserved.
            </p>
            {error.message ? (
              <p style={{ margin: "12px 0 0", color: "rgba(254, 243, 199, 0.6)", fontSize: "12px", lineHeight: 1.5 }}>{error.message}</p>
            ) : null}
            <div style={{ marginTop: "20px", display: "flex", flexWrap: "wrap", gap: "10px" }}>
              <button
                type="button"
                onClick={() => window.location.reload()}
                style={{ border: 0, borderRadius: "10px", background: "#f4f4f5", color: "#09090b", cursor: "pointer", fontSize: "14px", fontWeight: 700, padding: "10px 14px" }}
              >
                Reload
              </button>
              <button
                type="button"
                onClick={() => void copyReport()}
                style={{ border: "1px solid rgba(255, 255, 255, 0.14)", borderRadius: "10px", background: "rgba(255, 255, 255, 0.04)", color: "#f4f4f5", cursor: "pointer", fontSize: "14px", fontWeight: 700, padding: "10px 14px" }}
              >
                {copied ? "Copied report" : "Copy debug report"}
              </button>
            </div>
          </section>
        </main>
      </body>
    </html>
  );
}
