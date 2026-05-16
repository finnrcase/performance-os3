"""Safe local and deployed integration diagnostics.

Run locally:
    python backend/scripts/check_integrations.py

Run against production:
    python backend/scripts/check_integrations.py --base-url https://api-production-b3ff.up.railway.app
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_local_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except Exception:
        return


def _component_lines(name: str, component: dict[str, Any]) -> list[str]:
    missing = ", ".join(component.get("missing_env_vars", []) or []) or "none"
    action = component.get("user_action_message") or ""
    lines = [
        f"{name}: {component.get('status', 'unknown')} - {component.get('message', '')}",
        f"  configured: {component.get('configured', False)}",
        f"  missing env vars: {missing}",
    ]
    if component.get("last_successful_sync"):
        lines.append(f"  last sync: {component['last_successful_sync']}")
    if component.get("latest_record"):
        lines.append(f"  latest record: {component['latest_record']}")
    if component.get("reconnect_required"):
        lines.append("  reconnect required: yes")
    if action:
        lines.append(f"  action: {action}")
    return lines


def _print_report(report: dict[str, Any], raw_json: bool) -> None:
    if raw_json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    print("Performance OS integration diagnostics")
    if "overall_status" not in report:
        print("overall: legacy_endpoint")
        print("The deployed /api/integrations/status endpoint does not expose the new diagnostic schema yet.")
        print("Push this commit to main and let Railway redeploy, then run this command again.")
        return
    print(f"overall: {report.get('overall_status', 'unknown')}")
    print(f"environment: {report.get('environment', 'unknown')}")
    print(f"checked_at: {report.get('checked_at', '')}")
    print("")
    for key in ["backend", "database", "frontend", "openai", "strava", "hevy", "withings"]:
        component = report.get(key)
        if isinstance(component, dict):
            print("\n".join(_component_lines(key, component)))
            print("")
    other = report.get("other_integrations", {})
    if isinstance(other, dict) and other:
        print("other integrations:")
        for name, component in other.items():
            if isinstance(component, dict):
                print("\n".join(_component_lines(f"  {name}", component)))
        print("")
    actions = report.get("required_user_actions", []) or []
    if actions:
        print("required user actions:")
        for action in actions:
            print(f"- {action}")
    else:
        print("required user actions: none")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Performance OS integrations without printing secrets.")
    parser.add_argument("--base-url", help="Fetch diagnostics from a deployed backend base URL instead of checking local env.")
    parser.add_argument("--json", action="store_true", help="Print the raw safe JSON report.")
    parser.add_argument("--no-external-checks", action="store_true", help="Skip live OpenAI/Hevy checks for local diagnostics.")
    args = parser.parse_args()

    if args.base_url:
        from src.integration_health import fetch_remote_integration_status

        report = fetch_remote_integration_status(args.base_url)
    else:
        _load_local_env()
        from src.integration_health import build_integration_status_report

        report = build_integration_status_report(run_external_checks=not args.no_external_checks)
    _print_report(report, args.json)
    return 0 if report.get("overall_status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
