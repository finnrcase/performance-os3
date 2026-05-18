import os

from fastapi.testclient import TestClient

from backend.routes.utils import ACCESS_COOKIE, create_session_token


TEST_APP_PASSWORD = "test-password"
TEST_SESSION_SECRET = "test-session-secret"


def configure_test_auth(client: TestClient) -> None:
    os.environ["APP_PASSWORD"] = TEST_APP_PASSWORD
    os.environ["SESSION_SECRET"] = TEST_SESSION_SECRET
    client.cookies.set(ACCESS_COOKIE, create_session_token(TEST_SESSION_SECRET))
