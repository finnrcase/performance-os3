import * as Sentry from "@sentry/nextjs";
import { sentryOptions } from "./sentry.shared";

const options = sentryOptions();

if (options.dsn) {
  Sentry.init(options as Parameters<typeof Sentry.init>[0]);
}
