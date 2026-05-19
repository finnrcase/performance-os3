const SECRET_KEY_PATTERN = /(password|secret|token|api[_-]?key|client[_-]?secret|database_url)/i;

function scrubValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.slice(0, 50).map(scrubValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        SECRET_KEY_PATTERN.test(key) ? "[redacted]" : scrubValue(item),
      ]),
    );
  }
  if (typeof value === "string" && value.length > 1200) return `${value.slice(0, 1200)}...`;
  return value;
}

export function sentryOptions() {
  return {
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN || process.env.SENTRY_DSN,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || process.env.SENTRY_ENVIRONMENT || process.env.NODE_ENV,
    release: process.env.NEXT_PUBLIC_SENTRY_RELEASE || process.env.SENTRY_RELEASE || process.env.VERCEL_GIT_COMMIT_SHA,
    tracesSampleRate: Number(process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE ?? process.env.SENTRY_TRACES_SAMPLE_RATE ?? 0.1),
    replaysSessionSampleRate: Number(process.env.NEXT_PUBLIC_SENTRY_REPLAYS_SESSION_SAMPLE_RATE ?? 0),
    replaysOnErrorSampleRate: Number(process.env.NEXT_PUBLIC_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE ?? 0.1),
    sendDefaultPii: false,
    beforeSend(event: unknown, hint: unknown) {
      void hint;
      return scrubValue(event);
    },
  };
}
