"""Shared pytest fixtures for the CORA backend.

Isolation guarantees (autouse, so they apply to every test):
- No network: any outbound socket connection raises, so a real API call that
  slips into the code fails the test loudly instead of silently going out.
- No API keys: LLM-provider key env vars are removed, so no test can depend
  on a real key being present.
- No local configuration: CORA_* variables are removed, so a developer's own
  backend/.env (loaded by main.py) can't change what the tests do.

Mocks for external services (the LLM client) belong here alongside these guards.
"""

import copy
import json
import os
import socket
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

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

# ANTHROPIC_AUTH_TOKEN is a second credential the Anthropic SDK accepts.
# ANTHROPIC_API_KEY is cleared too: the SDK would read it if our code ever stopped
# passing the key explicitly.
API_KEY_VARS = ("LLM_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY")
# Settings without the CORA_ prefix (names shared with main, PR #46).
SETTINGS_VARS = ("EXTRACTOR", "LLM_MODEL", "LLM_TIMEOUT", "LLM_RETRIES")


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


@pytest.fixture(autouse=True)
def no_local_config(monkeypatch):
    # Tests start from the defaults (keyword extractor) and opt in to anything
    # else with monkeypatch.setenv.
    for var in [v for v in os.environ if v.startswith("CORA_")] + list(SETTINGS_VARS):
        monkeypatch.delenv(var, raising=False)
    # A developer's .env may point at the real Supabase database. Tests must
    # never use it: persistence is off unless a test asks for the `db` fixture.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)


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


# ---------- PDFs built in memory ----------

@pytest.fixture
def make_pdf():
    """Build a text PDF from a list of page texts, without touching disk."""

    def _make(pages) -> bytes:
        doc = pymupdf.open()
        for text in pages:
            doc.new_page().insert_text((50, 72), text, fontsize=10)
        data = doc.tobytes()
        doc.close()
        return data

    return _make


def _draw_table(page, rows, x0=40, y0=60, label_width=160, col_width=72, row_height=16):
    """Draw a ruled table, the way protocols lay out a Schedule of Activities.

    None in a row means "merged with the cell to the left": the dividing line
    isn't drawn, so PyMuPDF reads one cell spanning both columns. Text after
    "^" is drawn small and raised, like a footnote letter.
    """
    ncols = len(rows[0])
    xs = [x0, x0 + label_width] + [x0 + label_width + col_width * k for k in range(1, ncols)]
    for r, row in enumerate(rows):
        y = y0 + r * row_height
        page.draw_line((xs[0], y), (xs[-1], y))
        for c in range(ncols + 1):
            if c in (0, ncols) or row[c] is not None:
                page.draw_line((xs[c], y), (xs[c], y + row_height))
        for c, text in enumerate(row):
            if not text:
                continue
            main, _, sup = text.partition("^")
            page.insert_text((xs[c] + 3, y + row_height - 5), main, fontsize=7)
            if sup:
                width = pymupdf.get_text_length(main, fontsize=7)
                page.insert_text((xs[c] + 3 + width, y + row_height - 8), sup, fontsize=4.5)
    bottom = y0 + len(rows) * row_height
    page.draw_line((xs[0], bottom), (xs[-1], bottom))


@pytest.fixture
def make_table_pdf():
    """Build a landscape PDF from (text, table rows) pages; rows may be None."""

    def _make(pages) -> bytes:
        doc = pymupdf.open()
        for text, rows in pages:
            page = doc.new_page(width=792, height=612)
            page.insert_text((40, 40), text, fontsize=10)
            if rows:
                _draw_table(page, rows)
        data = doc.tobytes()
        doc.close()
        return data

    return _make


# ---------- the mocked LLM ----------
#
# Why a fake client instead of the real SDK with patched HTTP: the unit under
# test is *our* code (prompt building, error mapping, validation, fallback).
# The fake stands in at the one seam where our code meets the SDK
# (llm_extractor.make_client), so tests are fast, free and deterministic, and
# the network guard above still fails any accidental real call.

# A good model answer for tests/fixtures/sample_protocol.pdf (one page).
LLM_PAYLOAD = {
    "protocol": {
        "title": "Synthetic Test Study of Drug X", "short_title": None, "protocol_number": None, "phase": "Phase 2",
        "sponsor": None, "therapeutic_area": None, "design": None, "enrollment": None, "duration": None,
    },
    "visits": [
        {"id": "V1", "name": "Screening", "day": "Day -28 to Day -1", "window": None, "type": None,
         "source_page": 1, "confidence": 0.95, "notes": None},
        {"id": "V2", "name": "Baseline", "day": "Day 1", "window": None, "type": None,
         "source_page": 1, "confidence": 0.95, "notes": None},
        {"id": "V3", "name": "Follow-up", "day": "Week 4", "window": "+/- 3 days", "type": None,
         "source_page": 1, "confidence": 0.9, "notes": None},
    ],
    "procedures": [
        {"name": "Informed consent", "category": "Regulatory", "visits": ["V1"],
         "source_page": 1, "confidence": 0.95, "notes": None},
        {"name": "Physical exam", "category": "Clinical", "visits": ["V1", "V2"],
         "source_page": 1, "confidence": 0.9, "notes": None},
        {"name": "Blood draw", "category": "Lab", "visits": ["V1", "V3"],
         "source_page": 1, "confidence": 0.6, "notes": "The analytes are not specified."},
    ],
    "staffing": [
        {"role": "Principal Investigator", "fte": None, "responsibilities": None, "qualifications": None,
         "source_page": 1, "confidence": 0.9, "notes": None},
        {"role": "Study Coordinator", "fte": None, "responsibilities": None, "qualifications": None,
         "source_page": 1, "confidence": 0.9, "notes": None},
    ],
    "safety": [
        {"event": "Serious adverse event", "timeline": "Within 24 hours", "recipient": "Sponsor",
         "method": None, "source_page": 1, "confidence": 0.9, "notes": None},
    ],
    "billing": [],
    "equipment": [],
    "pharmacy_involved": None,
    "pharmacy_items": [],
    "technology": [],
}


@pytest.fixture
def llm_payload() -> dict:
    """A fresh copy of a valid model answer, for tests to modify."""
    return copy.deepcopy(LLM_PAYLOAD)


class FakeLLM:
    """Stands in for anthropic.Anthropic. Plays back a script of responses.

    Each queued entry is one call's outcome:
    - a dict  -> the model's JSON answer
    - a str   -> the model's raw text (use for malformed JSON)
    - an Exception -> raised, as the SDK would raise it
    - ("stop", reason) -> a response with that stop_reason and no parsed output
    """

    def __init__(self):
        self.script = []
        self.calls = []    # keyword arguments of every messages.parse call
        self.options = []  # keyword arguments of every with_options call

    def queue(self, *entries):
        self.script.extend(entries)
        return self

    # --- the part of the SDK surface our code uses ---
    @property
    def messages(self):
        return self

    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        assert self.script, "FakeLLM was called more times than the test queued responses for"
        entry = self.script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        if isinstance(entry, tuple) and entry[0] == "stop":
            return SimpleNamespace(stop_reason=entry[1], content=[])
        text = entry if isinstance(entry, str) else json.dumps(entry)
        # Exactly what the real SDK does with the reply: validate the JSON
        # against the output_format model (raises pydantic.ValidationError).
        parsed = TypeAdapter(kwargs["output_format"]).validate_json(text)
        block = SimpleNamespace(type="text", text=text, parsed_output=parsed)
        return SimpleNamespace(stop_reason="end_turn", content=[block])


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the Anthropic client with a FakeLLM and return it."""
    import llm_extractor
    import pipeline

    fake = FakeLLM()
    monkeypatch.setattr(llm_extractor, "make_client", lambda settings: fake)
    # Retries sleep before the second attempt; skip the wait in tests.
    monkeypatch.setattr(pipeline, "_sleep", lambda seconds: None)
    return fake


@pytest.fixture
def llm_mode(monkeypatch, fake_llm):
    """Switch the app to the Claude extractor, backed by the FakeLLM."""
    monkeypatch.setenv("EXTRACTOR", "llm")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-real")
    return fake_llm


@pytest.fixture
def api_error():
    """Build the exceptions the Anthropic SDK raises, without any network."""
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    by_status = {
        400: anthropic.BadRequestError,
        401: anthropic.AuthenticationError,
        403: anthropic.PermissionDeniedError,
        404: anthropic.NotFoundError,
        429: anthropic.RateLimitError,
        500: anthropic.InternalServerError,
        529: anthropic.OverloadedError,
    }

    def _make(kind, body=None, headers=None, message="provider said something"):
        if kind == "timeout":
            return anthropic.APITimeoutError(request)
        if kind == "connection":
            return anthropic.APIConnectionError(request=request)
        response = httpx2.Response(kind, request=request, headers=headers or {}, json=body or {})
        return by_status[kind](message, response=response, body=body)

    return _make


# ---------- database (in-memory SQLite, never Supabase) ----------

@pytest.fixture
def db_on(monkeypatch):
    """Turn persistence on, backed by a fresh in-memory SQLite database."""
    import db
    from db_models import Base

    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    db.reset_engine()
    Base.metadata.create_all(db.get_engine())
    yield db
    db.reset_engine()


REVIEWER_A = "11111111-1111-4111-8111-111111111111"
REVIEWER_B = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def as_reviewer():
    """Headers identifying a reviewer, as the browser sends them."""

    def _headers(reviewer_id=REVIEWER_A, name="Reviewer A"):
        return {"X-Reviewer-Id": reviewer_id, "X-Reviewer-Name": name}

    return _headers
