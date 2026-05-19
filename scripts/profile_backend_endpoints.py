"""Profile critical FastAPI endpoints with pyinstrument.

This runs the app in-process through TestClient so we can quickly identify
Python-level bottlenecks without involving Vercel/Railway networking. It is
safe for local diagnostics and writes profile text files under outputs/profiles.
"""

from __future__ import annotations

import os
import re
import sys
import time
from multiprocessing import Process, Queue
from pathlib import Path

from pyinstrument import Profiler


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = PROJECT_ROOT / "outputs" / "profiles"
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("APP_PASSWORD", "profile-password")
os.environ.setdefault("SESSION_SECRET", "profile-session-secret-for-performance-os")
os.environ.setdefault("SENTRY_DSN", "")
os.environ.setdefault("NEXT_PUBLIC_SENTRY_DSN", "")
os.environ["DATABASE_URL"] = os.getenv("PROFILE_DATABASE_URL", "")

from src.storage import count_dataframe_rows  # noqa: E402
from src.training import TRAINING_LOG_PATH, load_live_training_log, training_raw_window_days  # noqa: E402
from src.nutrition import NUTRITION_LOG_PATH  # noqa: E402
from src.body_metrics import BODY_METRICS_PATH  # noqa: E402
from src.recovery import RECOVERY_LOG_PATH, SLEEP_ENTRIES_PATH  # noqa: E402


ENDPOINTS = [
    "/api/dashboard/core",
    "/api/dashboard",
    "/api/training/history?limit=50&days=180",
    "/api/training/strength-trends?date_range=12w",
    "/api/goals",
]
ENDPOINT_TIMEOUT_SECONDS = int(os.getenv("PROFILE_ENDPOINT_TIMEOUT_SECONDS", "30"))


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


def first_profile_function(profile_text: str) -> str:
    for line in profile_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("_") or stripped.startswith("Profile at") or stripped.startswith("Samples:"):
            continue
        if " " in stripped and (".py:" in stripped or "<" in stripped):
            return stripped[:220]
    return "see profile output"


def row_counts() -> dict[str, int]:
    raw_window_days = training_raw_window_days()
    try:
        recent_training_rows = int(len(load_live_training_log(days=raw_window_days, max_rows=100000)))
    except Exception:
        recent_training_rows = -1
    return {
        "training_rows_total": count_dataframe_rows("training_log", TRAINING_LOG_PATH),
        "training_rows_recent_window": recent_training_rows,
        "nutrition_rows": count_dataframe_rows("nutrition_log", NUTRITION_LOG_PATH),
        "body_metric_rows": count_dataframe_rows("body_metrics", BODY_METRICS_PATH),
        "recovery_rows": count_dataframe_rows("recovery_log", RECOVERY_LOG_PATH),
        "sleep_rows": count_dataframe_rows("sleep_entries", SLEEP_ENTRIES_PATH),
    }


def profile_endpoint(endpoint: str, queue: Queue) -> None:
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    login = client.post("/api/auth/login", json={"password": os.environ["APP_PASSWORD"]})
    if login.status_code != 200:
        queue.put({"endpoint": endpoint, "status": login.status_code, "duration_ms": 0, "error": f"login failed: {login.text}"})
        return

    profiler = Profiler(interval=0.001)
    started = time.perf_counter()
    profiler.start()
    response = client.get(endpoint)
    profiler.stop()
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    text_output = profiler.output_text(unicode=True, color=False, show_all=False)
    profile_path = PROFILE_DIR / f"{slugify(endpoint)}.txt"
    profile_path.write_text(text_output, encoding="utf-8")
    queue.put(
        {
            "endpoint": endpoint,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "bytes": len(response.content),
            "top_function": first_profile_function(text_output),
            "profile": str(profile_path.relative_to(PROJECT_ROOT)),
        }
    )


def main() -> int:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    counts = row_counts()
    print("Row counts:")
    for key, value in counts.items():
        print(f"  {key}: {value}", flush=True)
    print("", flush=True)

    report: list[dict[str, object]] = []
    for endpoint in ENDPOINTS:
        print(f"Profiling {endpoint}...", flush=True)
        queue: Queue = Queue()
        process = Process(target=profile_endpoint, args=(endpoint, queue))
        started = time.perf_counter()
        process.start()
        process.join(ENDPOINT_TIMEOUT_SECONDS)
        if process.is_alive():
            process.terminate()
            process.join(5)
            report.append(
                {
                    "endpoint": endpoint,
                    "status": "timeout",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "bytes": 0,
                    "top_function": f"endpoint exceeded {ENDPOINT_TIMEOUT_SECONDS}s; run individually with a higher timeout",
                    "profile": "",
                }
            )
            continue
        report.append(queue.get() if not queue.empty() else {"endpoint": endpoint, "status": "error", "duration_ms": 0, "bytes": 0, "top_function": "no profile returned", "profile": ""})

    print("Endpoint profile report:")
    for item in sorted(report, key=lambda row: float(row["duration_ms"]), reverse=True):
        print(
            f"  {item['endpoint']} status={item['status']} duration={item['duration_ms']}ms "
            f"bytes={item['bytes']} top={item['top_function']} profile={item['profile']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
