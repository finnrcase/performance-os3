import os
import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import PUBLIC_API_PATHS, app
from tests.auth_helpers import TEST_APP_PASSWORD, TEST_SESSION_SECRET


WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PATH_PARAM_EXAMPLES = {
    "food_log_id": "food-log-id",
    "shortcut_id": "shortcut-id",
    "template_name": "Template",
    "food_name": "Food",
}


def _concrete_path(path: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return PATH_PARAM_EXAMPLES.get(name, "value")

    return re.sub(r"\{([^}]+)\}", replace, path)


class ApiAuthSecurityTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_private_api_reads_require_session_cookie(self):
        with patch.dict(os.environ, {"APP_PASSWORD": TEST_APP_PASSWORD, "SESSION_SECRET": TEST_SESSION_SECRET}, clear=True):
            response = self.client.get("/api/dashboard")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Authentication required")

    def test_all_private_api_write_routes_require_session_cookie(self):
        failures = []
        with patch.dict(os.environ, {"APP_PASSWORD": TEST_APP_PASSWORD, "SESSION_SECRET": TEST_SESSION_SECRET}, clear=True):
            for route in app.routes:
                methods = set(getattr(route, "methods", set()) or set()) & WRITE_METHODS
                path = getattr(route, "path", "")
                if not path.startswith("/api/") or (path.rstrip("/") or "/") in PUBLIC_API_PATHS:
                    continue
                for method in sorted(methods):
                    response = self.client.request(method, _concrete_path(path), json={})
                    if response.status_code != 401 or response.json().get("detail") != "Authentication required":
                        failures.append(f"{method} {path} -> {response.status_code} {response.text[:120]}")

        self.assertEqual(failures, [])

    def test_health_and_oauth_callbacks_remain_public(self):
        with patch.dict(os.environ, {"APP_PASSWORD": TEST_APP_PASSWORD, "SESSION_SECRET": TEST_SESSION_SECRET}, clear=True):
            health = self.client.get("/health")
            strava = self.client.get("/api/strava/callback", follow_redirects=False)
            withings = self.client.get("/api/withings/callback")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(strava.status_code, 303)
        self.assertEqual(withings.status_code, 200)
        self.assertEqual(withings.json()["provider"], "withings")


if __name__ == "__main__":
    unittest.main()
