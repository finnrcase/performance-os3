"""Initialize the production Postgres schema for Performance OS."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paths import PROJECT_ROOT
from src.storage import ensure_database_schema, use_database


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    if not use_database():
        raise SystemExit("DATABASE_URL is required to initialize production storage.")
    ensure_database_schema()
    print("Performance OS database schema is ready.")


if __name__ == "__main__":
    main()
