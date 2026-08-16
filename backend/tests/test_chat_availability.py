"""
The app must boot without a Gemini API key.

A missing chatbot key used to crash the whole application at import, because
gemini.py built its client at module level. Everything else in the app works
fine without that key, so these tests pin the behaviour down.
"""

import os
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai import gemini
from app.api import chat as chat_router


@pytest.fixture(autouse=True)
def reset_client(monkeypatch):
    """Clear the cached client so each test starts from a clean state."""
    monkeypatch.setattr(gemini, "_client", None)


def test_whole_app_boots_with_no_gemini_key():
    """
    The regression this file exists for: importing app.main with no API key.

    Runs in a SUBPROCESS on purpose. Doing it in-process would need
    importlib.reload(), which builds a new module object while app/api/chat.py
    still holds a reference to the old ChatUnavailableError class, so the
    `except` clause silently stops matching and other tests start failing.
    A separate interpreter is the honest way to test import-time behaviour.
    """
    env = {
        **os.environ,
        "GEMINI_API_KEY": "",
        "DATABASE_URL": "sqlite://",
        "JWT_SECRET_KEY": "test",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import app.main; print('booted')"],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert result.returncode == 0, f"app failed to import without a key:\n{result.stderr}"
    assert "booted" in result.stdout


def test_missing_key_raises_only_when_the_chatbot_is_used(monkeypatch):
    monkeypatch.setattr(gemini.settings, "GEMINI_API_KEY", "")
    with pytest.raises(gemini.ChatUnavailableError, match="GEMINI_API_KEY"):
        gemini.get_client()


def test_chat_endpoint_returns_503_when_unconfigured(monkeypatch):
    """Not configured is a different failure from upstream broken."""
    monkeypatch.setattr(gemini.settings, "GEMINI_API_KEY", "")

    app = FastAPI()
    app.include_router(chat_router.router, prefix="/api/v1")

    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"message": "hi"})

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_client_is_built_once_and_reused(monkeypatch):
    """Lazy, but still one client per process rather than one per request."""
    monkeypatch.setattr(gemini.settings, "GEMINI_API_KEY", "fake-key")
    built = []

    class FakeClient:
        def __init__(self, api_key):
            built.append(api_key)

    monkeypatch.setattr(gemini.genai, "Client", FakeClient)

    first = gemini.get_client()
    second = gemini.get_client()

    assert first is second
    assert built == ["fake-key"]  # constructed exactly once
