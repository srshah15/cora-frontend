"""Shared pytest fixtures for the CORA backend.

Isolation guarantees (autouse, so they apply to every test):
- No network: any outbound socket connection raises, so a real API call that
  slips into the code fails the test loudly instead of silently going out.
- No API keys: LLM-provider key env vars are removed, so no test can depend
  on a real key being present.

The backend has no LLM step yet (extraction is keyword-based, see extract.py).
When one is added, put its mock here alongside these guards.
"""

import json
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_PDF = FIXTURES / "sample_protocol.pdf"
# sample_plan.json is a copy of window.SAMPLE_PLAN in frontend/sample-data.js
# (JSON can't hold comments, so the note lives here). If sample-data.js
# changes, regenerate it from the repo root:
#   node -e 'global.window={}; require("./frontend/sample-data.js");
#     console.log(JSON.stringify(window.SAMPLE_PLAN, null, 2))' \
#     > backend/tests/fixtures/sample_plan.json
SAMPLE_PLAN = FIXTURES / "sample_plan.json"

API_KEY_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")


class NetworkAccessError(RuntimeError):
    """Raised when a test tries to open a network connection."""


def _blocked(*args, **kwargs):
    raise NetworkAccessError(
        f"Network access attempted during tests: {args!r}. "
        "Mock the external call instead of hitting a real service."
    )


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    # TestClient talks to the app in-process, so it never opens a socket.
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


@pytest.fixture(autouse=True)
def no_api_keys(monkeypatch):
    for var in API_KEY_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    return SAMPLE_PDF.read_bytes()


@pytest.fixture
def sample_plan() -> dict:
    """The frontend's sample plan as a plain dict (fresh copy per test)."""
    return json.loads(SAMPLE_PLAN.read_text())
